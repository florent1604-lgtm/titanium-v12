import { createState, reduce } from './state.mjs';

const PAGE_LIMIT = 500;
const RECONNECT_DELAYS = [1000, 2000, 5000, 10000];

export class CollabClient {
  constructor(options = {}) {
    this.fetch = options.fetch ?? globalThis.fetch?.bind(globalThis);
    this.socketFactory = options.socketFactory ?? defaultSocketFactory;
    this.setTimeout = options.setTimeout ?? globalThis.setTimeout.bind(globalThis);
    this.clearTimeout = options.clearTimeout ?? globalThis.clearTimeout.bind(globalThis);
    this.abortControllerFactory = options.abortControllerFactory ??
      (() => new globalThis.AbortController());
    this.onStatus = options.onStatus ?? (() => {});
    this.state = options.state ?? createState();
    this.lastConfirmedOffset = 0;
    this.connectionStatus = 'idle';
    this.socket = null;
    this.reconnectTimer = null;
    this.reconnectAttempt = 0;
    this.requestControllers = new Set();
    this.stopped = true;
    this.generation = 0;
    this.onMessage = () => {};

    if (typeof this.fetch !== 'function') {
      throw new TypeError('A fetch implementation is required');
    }
    if (typeof this.socketFactory !== 'function') {
      throw new TypeError('A socketFactory implementation is required');
    }
  }

  async replay(afterOffset = this.lastConfirmedOffset, operation = {}) {
    let offset = validOffset(afterOffset, 'afterOffset');
    const generation = operation.generation ?? this.generation;
    const requireActive = operation.requireActive ?? false;
    const replayed = [];

    while (true) {
      const messages = await this.requestMessages(
        `/v1/messages?after_offset=${offset}&limit=${PAGE_LIMIT}`,
        { generation, requireActive },
      );
      if (messages === null) return [];
      if (!this.isCurrent(generation, requireActive)) return [];
      this.confirm(messages);
      replayed.push(...messages);
      if (messages.length < PAGE_LIMIT) return replayed;

      const nextOffset = messages.at(-1).global_offset;
      if (nextOffset <= offset) {
        throw new TypeError('CollabHub replay did not advance its offset');
      }
      offset = nextOffset;
    }
  }

  async loadOlder(beforeOffset) {
    const offset = validOffset(beforeOffset, 'beforeOffset');
    const generation = this.generation;
    const messages = await this.requestMessages(
      `/v1/messages?before_offset=${offset}&limit=${PAGE_LIMIT}`,
      { generation, requireActive: false },
    );
    if (messages === null) return [];
    if (!this.isCurrent(generation, false)) return [];
    this.state = reduce(this.state, { type: 'messages.loaded', messages });
    return messages;
  }

  async connect(onMessage = this.onMessage) {
    if (typeof onMessage !== 'function') {
      throw new TypeError('onMessage must be a function');
    }

    this.cancelTransport();
    this.onMessage = onMessage;
    this.reconnectAttempt = 0;
    this.stopped = false;
    const generation = this.generation;
    try {
      await this.replayAndOpen(generation);
    } catch {
      if (this.isCurrent(generation, true)) this.scheduleReconnect(generation);
    }
    return this;
  }

  async start(afterOffset = 0, onMessage = this.onMessage) {
    const offset = validOffset(afterOffset, 'afterOffset');
    this.cancelTransport();
    this.lastConfirmedOffset = offset;
    return this.connect(onMessage);
  }

  stop() {
    this.cancelTransport();
    this.setStatus('stopped');
  }

  cancelTransport() {
    this.stopped = true;
    this.generation += 1;
    if (this.reconnectTimer !== null) {
      const reconnectTimer = this.reconnectTimer;
      this.reconnectTimer = null;
      this.clearTimeout(reconnectTimer.handle);
    }
    for (const controller of this.requestControllers) controller.abort();
    this.requestControllers.clear();
    const socket = this.socket;
    this.socket = null;
    if (socket && typeof socket.close === 'function') socket.close();
  }

  async requestMessages(url, operation = {}) {
    const generation = operation.generation ?? this.generation;
    const requireActive = operation.requireActive ?? false;
    const controller = this.abortControllerFactory();
    if (!controller || typeof controller.abort !== 'function') {
      throw new TypeError('abortControllerFactory must return an AbortController');
    }
    if (!this.isCurrent(generation, requireActive)) {
      controller.abort();
      return null;
    }
    this.requestControllers.add(controller);
    try {
      const response = await this.fetch(url, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (!response?.ok) {
        throw new Error(
          `CollabHub request failed (${response?.status ?? 'UNKNOWN'})`,
        );
      }
      const payload = await response.json();
      if (!isPlainObject(payload) || !Array.isArray(payload.messages)) {
        throw new TypeError('CollabHub returned an invalid message page');
      }
      return payload.messages.map(validateMessage);
    } finally {
      this.requestControllers.delete(controller);
    }
  }

  confirm(messages) {
    this.state = reduce(this.state, { type: 'messages.loaded', messages });
    for (const item of messages) {
      this.lastConfirmedOffset = Math.max(
        this.lastConfirmedOffset,
        item.global_offset,
      );
    }
  }

  async replayAndOpen(generation) {
    if (!this.isCurrent(generation, true)) return;
    this.setStatus(this.reconnectAttempt === 0 ? 'replaying' : 'reconnecting');
    if (!this.isCurrent(generation, true)) return;
    await this.replay(this.lastConfirmedOffset, {
      generation,
      requireActive: true,
    });
    if (!this.isCurrent(generation, true)) return;
    this.openSocket(generation);
  }

  openSocket(generation) {
    this.setStatus('connecting');
    if (!this.isCurrent(generation, true)) return;
    const socket = this.socketFactory(
      `/v1/ws?after_offset=${this.lastConfirmedOffset}`,
    );
    if (!this.isCurrent(generation, true)) {
      if (socket && typeof socket.close === 'function') socket.close();
      return;
    }
    if (!socket || typeof socket !== 'object') {
      throw new TypeError('socketFactory must return a socket');
    }
    this.socket = socket;

    socket.onopen = () => {
      if (this.isCurrent(generation, true)) {
        this.reconnectAttempt = 0;
        this.setStatus('connected');
      }
    };
    socket.onmessage = (event) => {
      if (this.stopped || generation !== this.generation) return;
      let item;
      try {
        item = validateMessage(JSON.parse(event.data));
        this.confirm([item]);
        this.reconnectAttempt = 0;
      } catch {
        this.setStatus('error');
        if (
          this.isCurrent(generation, true) &&
          this.socket === socket &&
          typeof socket.close === 'function'
        ) {
          socket.close();
        }
        return;
      }
      try {
        this.onMessage(item, this.state);
      } catch {
        // View callbacks never change transport state or trigger retries.
      }
    };
    socket.onerror = () => {
      if (this.isCurrent(generation, true)) {
        this.setStatus('error');
        if (
          this.isCurrent(generation, true) &&
          this.socket === socket &&
          typeof socket.close === 'function'
        ) {
          socket.close();
        }
      }
    };
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null;
      if (this.isCurrent(generation, true)) {
        this.scheduleReconnect(generation);
      }
    };
  }

  scheduleReconnect(generation) {
    if (this.reconnectTimer !== null || this.stopped) return;
    const delay = RECONNECT_DELAYS[
      Math.min(this.reconnectAttempt, RECONNECT_DELAYS.length - 1)
    ];
    this.reconnectAttempt += 1;
    this.setStatus('reconnecting');
    if (!this.isCurrent(generation, true)) return;
    const timerRecord = { fired: false, handle: null };
    const reconnectTimer = this.setTimeout(async () => {
      timerRecord.fired = true;
      if (this.reconnectTimer !== timerRecord) return;
      this.reconnectTimer = null;
      if (!this.isCurrent(generation, true)) return;
      try {
        await this.replayAndOpen(generation);
      } catch {
        if (this.isCurrent(generation, true)) {
          this.setStatus('error');
          if (this.isCurrent(generation, true)) {
            this.scheduleReconnect(generation);
          }
        }
      }
    }, delay);
    timerRecord.handle = reconnectTimer;
    if (!this.isCurrent(generation, true) || timerRecord.fired) {
      this.clearTimeout(reconnectTimer);
      return;
    }
    this.reconnectTimer = timerRecord;
  }

  setStatus(status) {
    this.connectionStatus = status;
    try {
      this.onStatus(status);
    } catch {
      // Status observers cannot interfere with the transport lifecycle.
    }
  }

  isCurrent(generation, requireActive) {
    return generation === this.generation && (!requireActive || !this.stopped);
  }
}

function validOffset(value, name) {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) {
    throw new RangeError(`${name} must be a non-negative safe integer`);
  }
  return value;
}

function validateMessage(value) {
  if (!isPlainObject(value)) throw new TypeError('Invalid CollabHub message');
  if (
    typeof value.message_id !== 'string' ||
    value.message_id.length === 0 ||
    value.message_id.length > 256
  ) {
    throw new TypeError('Invalid CollabHub message_id');
  }
  validOffset(value.global_offset, 'global_offset');
  return { ...value };
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function defaultSocketFactory(path) {
  if (typeof globalThis.WebSocket !== 'function') {
    throw new TypeError('A WebSocket implementation is required');
  }
  return new globalThis.WebSocket(toWebSocketUrl(path));
}

function toWebSocketUrl(path) {
  const location = globalThis.location;
  if (!location?.host) throw new TypeError('A browser location is required');
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${location.host}${path}`;
}

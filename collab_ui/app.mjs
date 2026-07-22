import { CollabClient } from './api.mjs';

export function createApp(options = {}) {
  const client = options.client ?? new CollabClient(options.clientOptions);
  const listeners = new Set();
  const previousStatusHandler = client.onStatus;

  client.onStatus = (status) => {
    try {
      if (typeof previousStatusHandler === 'function') previousStatusHandler(status);
    } finally {
      notify();
    }
  };

  function snapshot() {
    return {
      connectionStatus: client.connectionStatus,
      state: client.state,
    };
  }

  function notify() {
    const current = snapshot();
    for (const listener of listeners) {
      try {
        listener(current);
      } catch {
        // A view failure must not alter the realtime transport lifecycle.
      }
    }
  }

  async function start(afterOffset = 0) {
    await client.start(afterOffset, () => notify());
    notify();
    return snapshot();
  }

  async function loadOlder(beforeOffset) {
    const messages = await client.loadOlder(beforeOffset);
    notify();
    return messages;
  }

  function stop() {
    client.stop();
  }

  function subscribe(listener) {
    if (typeof listener !== 'function') {
      throw new TypeError('listener must be a function');
    }
    listeners.add(listener);
    try {
      listener(snapshot());
    } catch {
      // Keep the subscription isolated just like later notifications.
    }
    return () => listeners.delete(listener);
  }

  return Object.freeze({ loadOlder, snapshot, start, stop, subscribe });
}

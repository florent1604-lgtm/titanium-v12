import assert from 'node:assert/strict';
import test from 'node:test';

import { CollabClient } from '../../collab_ui/api.mjs';
import {
  HostBridge,
  createWebViewBridge,
} from '../../collab_ui/host_bridge.mjs';
import { createApp } from '../../collab_ui/app.mjs';

function message(globalOffset, overrides = {}) {
  return {
    message_id: `message-${globalOffset}`,
    global_offset: globalOffset,
    created_at: '2026-07-22T10:00:00Z',
    principal: 'codex',
    target: 'team',
    kind: 'status',
    content: `Message ${globalOffset}`,
    ...overrides,
  };
}

function response(messages) {
  return {
    ok: true,
    async json() {
      return { messages };
    },
  };
}

function fakeFetch(pages, calls) {
  return async (url) => {
    calls.push(url);
    assert.ok(pages.length > 0, `unexpected fetch: ${url}`);
    return response(pages.shift());
  };
}

class FakeSocket {
  closeCalls = 0;

  close() {
    this.closeCalls += 1;
    this.onclose?.({ code: 1000 });
  }

  emitClose() {
    this.onclose?.({ code: 1006 });
  }

  emitMessage(value) {
    this.onmessage?.({ data: JSON.stringify(value) });
  }
}

function fakeSockets(events) {
  const sockets = [];
  const factory = (url) => {
    events.push(`socket:${url}`);
    const socket = new FakeSocket();
    sockets.push(socket);
    return socket;
  };
  return { factory, sockets };
}

function fakeScheduler() {
  const pending = [];
  const delays = [];
  return {
    delays,
    setTimeout(callback, delay) {
      const timer = { callback, cancelled: false };
      delays.push(delay);
      pending.push(timer);
      return timer;
    },
    clearTimeout(timer) {
      timer.cancelled = true;
    },
    async runNext() {
      const timer = pending.shift();
      assert.ok(timer, 'expected a pending reconnect');
      if (!timer.cancelled) await timer.callback();
    },
  };
}

test('replays after the last confirmed offset before opening and reconnecting the socket', async () => {
  const events = [];
  const calls = [];
  const scheduler = fakeScheduler();
  const sockets = fakeSockets(events);
  const fetch = async (url) => {
    calls.push(url);
    events.push(`fetch:${url}`);
    return response(
      calls.length === 1 ? [message(341), message(342)] : [message(343)],
    );
  };
  const client = new CollabClient({
    fetch,
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.start(340);

  assert.deepEqual(events, [
    'fetch:/v1/messages?after_offset=340&limit=500',
    'socket:/v1/ws?after_offset=342',
  ]);
  sockets.sockets[0].emitClose();
  assert.deepEqual(scheduler.delays, [1000]);

  await scheduler.runNext();

  assert.deepEqual(events.slice(2), [
    'fetch:/v1/messages?after_offset=342&limit=500',
    'socket:/v1/ws?after_offset=343',
  ]);
  assert.equal(client.lastConfirmedOffset, 343);
});

test('drains every forward replay page before opening the socket', async () => {
  const calls = [];
  const sockets = fakeSockets([]);
  const firstPage = Array.from({ length: 500 }, (_value, index) =>
    message(index + 1));
  const client = new CollabClient({
    fetch: fakeFetch([firstPage, [message(501), message(502)]], calls),
    socketFactory: sockets.factory,
  });

  await client.start(0);

  assert.deepEqual(calls, [
    '/v1/messages?after_offset=0&limit=500',
    '/v1/messages?after_offset=500&limit=500',
  ]);
  assert.equal(client.state.messages.length, 502);
  assert.equal(client.lastConfirmedOffset, 502);
  client.stop();
});

test('deduplicates replay and socket overlap through shared state', async () => {
  const calls = [];
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: fakeFetch([[message(8), message(9)]], calls),
    socketFactory: sockets.factory,
  });

  await client.start(7);
  sockets.sockets[0].emitMessage(message(9));
  sockets.sockets[0].emitMessage(message(10));

  assert.deepEqual(
    client.state.messages.map((item) => item.global_offset),
    [8, 9, 10],
  );
  assert.equal(client.lastConfirmedOffset, 10);
  client.stop();
});

test('loads older pages to the beginning in increasing order without gaps or duplicates', async () => {
  const calls = [];
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: fakeFetch(
      [
        [message(4), message(5), message(6)],
        [message(1), message(2), message(3)],
        [],
      ],
      calls,
    ),
    socketFactory: sockets.factory,
  });

  await client.loadOlder(7);
  await client.loadOlder(4);
  const beginning = await client.loadOlder(1);

  assert.deepEqual(calls, [
    '/v1/messages?before_offset=7&limit=500',
    '/v1/messages?before_offset=4&limit=500',
    '/v1/messages?before_offset=1&limit=500',
  ]);
  assert.deepEqual(
    client.state.messages.map((item) => item.global_offset),
    [1, 2, 3, 4, 5, 6],
  );
  assert.deepEqual(beginning, []);
});

test('a stale older page cannot mutate state after cancellation', async () => {
  let finishPage;
  const client = new CollabClient({
    fetch: () => new Promise((resolve) => {
      finishPage = () => resolve(response([message(1)]));
    }),
    socketFactory: fakeSockets([]).factory,
  });

  const loading = client.loadOlder(2);
  await Promise.resolve();
  client.stop();
  finishPage();

  assert.deepEqual(await loading, []);
  assert.deepEqual(client.state.messages, []);
});

test('bounds reconnect transport backoff at 1, 2, 5, then 10 seconds', async () => {
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.start(0);
  for (let index = 0; index < 5; index += 1) {
    sockets.sockets[index].emitClose();
    await scheduler.runNext();
  }

  assert.deepEqual(scheduler.delays, [1000, 2000, 5000, 10000, 10000]);
  client.stop();
});

test('stop closes the socket and cancels a pending reconnect without opening another', async () => {
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.start(0);
  sockets.sockets[0].emitClose();
  client.stop();
  await scheduler.runNext();

  assert.equal(sockets.sockets.length, 1);
  assert.equal(sockets.sockets[0].closeCalls, 0);
  assert.equal(client.connectionStatus, 'stopped');
});

test('stop aborts an in-flight replay before any socket can open', async () => {
  let replaySignal;
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: (_url, options) => new Promise((_resolve, reject) => {
      replaySignal = options.signal;
      replaySignal?.addEventListener('abort', () => {
        const error = new Error('aborted');
        error.name = 'AbortError';
        reject(error);
      });
    }),
    socketFactory: sockets.factory,
  });

  const starting = client.start(0);
  await Promise.resolve();

  assert.ok(replaySignal, 'replay must receive an AbortSignal');
  client.stop();
  await starting;
  assert.equal(replaySignal.aborted, true);
  assert.equal(sockets.sockets.length, 0);
});

test('a stop inside abortControllerFactory aborts locally without starting fetch', async () => {
  let client;
  let fetchCalls = 0;
  const controller = new AbortController();
  client = new CollabClient({
    abortControllerFactory() {
      client.stop();
      return controller;
    },
    fetch: async () => {
      fetchCalls += 1;
      return response([]);
    },
    socketFactory: fakeSockets([]).factory,
  });

  await client.start(0);

  assert.equal(controller.signal.aborted, true);
  assert.equal(fetchCalls, 0);
  assert.equal(client.requestControllers.size, 0);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a stale replay cannot mutate state after stop when fetch ignores abort', async () => {
  let finishReplay;
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: () => new Promise((resolve) => {
      finishReplay = () => resolve(response([message(99)]));
    }),
    socketFactory: sockets.factory,
  });

  const starting = client.start(0);
  await Promise.resolve();
  client.stop();
  finishReplay();
  await starting;

  assert.equal(client.lastConfirmedOffset, 0);
  assert.deepEqual(client.state.messages, []);
  assert.equal(sockets.sockets.length, 0);
});

test('an older start cannot advance the confirmed offset of a newer start', async () => {
  const pending = [];
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: () => new Promise((resolve) => pending.push(resolve)),
    socketFactory: sockets.factory,
  });

  const olderStart = client.start(0);
  await Promise.resolve();
  const newerStart = client.start(10);
  await Promise.resolve();
  pending[1](response([message(11)]));
  await newerStart;
  pending[0](response([message(99)]));
  await olderStart;

  assert.equal(client.lastConfirmedOffset, 11);
  assert.deepEqual(
    client.state.messages.map((item) => item.global_offset),
    [11],
  );
  client.stop();
});

test('an onMessage exception never closes or retries the transport', async () => {
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.start(0, () => {
    throw new Error('render failed');
  });

  assert.doesNotThrow(() => sockets.sockets[0].emitMessage(message(1)));
  assert.equal(sockets.sockets[0].closeCalls, 0);
  assert.deepEqual(scheduler.delays, []);
  assert.equal(client.lastConfirmedOffset, 1);
  client.stop();
});

test('an initial replay failure enters bounded transport recovery', async () => {
  let attempts = 0;
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => {
      attempts += 1;
      if (attempts === 1) throw new Error('offline');
      return response([]);
    },
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.start(0);

  assert.deepEqual(scheduler.delays, [1000]);
  assert.equal(sockets.sockets.length, 0);
  assert.equal(client.connectionStatus, 'reconnecting');
  await scheduler.runNext();
  assert.equal(sockets.sockets.length, 1);
  client.stop();
});

test('a reentrant stop at replaying prevents the fetch from starting', async () => {
  let client;
  let fetchCalls = 0;
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  client = new CollabClient({
    fetch: async () => {
      fetchCalls += 1;
      return response([]);
    },
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
    onStatus(status) {
      if (status === 'replaying') client.stop();
    },
  });

  await client.start(0);

  assert.equal(fetchCalls, 0);
  assert.equal(sockets.sockets.length, 0);
  assert.deepEqual(scheduler.delays, []);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a reentrant stop at connecting prevents the socket from being created', async () => {
  let client;
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
    onStatus(status) {
      if (status === 'connecting') client.stop();
    },
  });

  await client.start(0);

  assert.equal(sockets.sockets.length, 0);
  assert.deepEqual(scheduler.delays, []);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a stop inside socketFactory closes the returned socket without retaining it', async () => {
  let client;
  let returnedSocket;
  client = new CollabClient({
    fetch: async () => response([]),
    socketFactory() {
      client.stop();
      returnedSocket = new FakeSocket();
      return returnedSocket;
    },
  });

  await client.start(0);

  assert.equal(client.socket, null);
  assert.equal(returnedSocket.closeCalls, 1);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a reentrant stop at reconnecting prevents a timer from being retained', async () => {
  let client;
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });
  await client.start(0);
  client.onStatus = (status) => {
    if (status === 'reconnecting') client.stop();
  };

  sockets.sockets[0].emitClose();

  assert.deepEqual(scheduler.delays, []);
  assert.equal(client.reconnectTimer, null);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a stop inside setTimeout clears the returned timer without retaining it', async () => {
  let client;
  const cleared = [];
  const timer = { id: 'reentrant-timer' };
  client = new CollabClient({
    fetch: async () => {
      throw new Error('offline');
    },
    socketFactory: fakeSockets([]).factory,
    setTimeout() {
      client.stop();
      return timer;
    },
    clearTimeout(handle) {
      cleared.push(handle);
    },
  });

  await client.start(0);

  assert.equal(client.reconnectTimer, null);
  assert.deepEqual(cleared, [timer]);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a stale timer callback cannot clear the current generation timer', async () => {
  const timers = [];
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout(callback) {
      const timer = { callback, cleared: false };
      timers.push(timer);
      return timer;
    },
    clearTimeout(timer) {
      timer.cleared = true;
    },
  });
  await client.start(0);
  sockets.sockets[0].emitClose();
  const staleTimer = timers[0];
  await client.connect();
  sockets.sockets[1].emitClose();
  const currentTimer = timers[1];

  await staleTimer.callback();
  assert.notEqual(client.reconnectTimer, null);
  client.stop();

  assert.equal(staleTimer.cleared, true);
  assert.equal(currentTimer.cleared, true);
  assert.equal(client.reconnectTimer, null);
});

test('a reentrant stop at reconnect replay prevents another fetch', async () => {
  let client;
  let fetchCalls = 0;
  let reconnectStatuses = 0;
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  client = new CollabClient({
    fetch: async () => {
      fetchCalls += 1;
      return response([]);
    },
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });
  await client.start(0);
  client.onStatus = (status) => {
    if (status !== 'reconnecting') return;
    reconnectStatuses += 1;
    if (reconnectStatuses === 2) client.stop();
  };
  sockets.sockets[0].emitClose();

  await scheduler.runNext();

  assert.equal(fetchCalls, 1);
  assert.equal(sockets.sockets.length, 1);
  assert.equal(client.reconnectTimer, null);
  assert.equal(client.connectionStatus, 'stopped');
});

test('a repeated connect replaces the previous transport without leaking a socket', async () => {
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
  });

  await client.connect();
  await client.connect();

  assert.equal(sockets.sockets.length, 2);
  assert.equal(sockets.sockets[0].closeCalls, 1);
  assert.deepEqual(scheduler.delays, []);
  client.stop();
});

test('rejects coerced offsets instead of accepting malformed protocol values', async () => {
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
  });

  await assert.rejects(client.start('0'), /non-negative safe integer/);
  await client.start(0);
  sockets.sockets[0].emitMessage(message(1, { global_offset: '1' }));

  assert.deepEqual(client.state.messages, []);
  assert.equal(sockets.sockets[0].closeCalls, 1);
  client.stop();
});

test('HostBridge forwards only the five allowlisted, schema-valid intentions', () => {
  const forwarded = [];
  const bridge = new HostBridge((intent) => forwarded.push(intent));
  const valid = [
    { type: 'chat.publish', content: 'Bonjour', task_id: 'UI_TASK_2' },
    { type: 'task.create', title: 'Revoir UI', owner: 'codex', priority: 'P2' },
    { type: 'task.retry.request', task_id: 'task-1' },
    { type: 'action.preview', action: 'service.health', parameters: {} },
    { type: 'host.open_vscode', path: 'C:\\workspace' },
  ];

  for (const intent of valid) bridge.postIntent(intent);

  assert.deepEqual(forwarded, valid);
});

test('HostBridge rejects unknown, malformed, and oversized intentions fail-closed', () => {
  const bridge = new HostBridge(() => assert.fail('must not forward'));

  assert.throws(
    () => bridge.postIntent({ type: 'registry.write.raw', payload: {} }),
    /not allowed/,
  );
  assert.throws(
    () => bridge.postIntent({ type: 'task.retry.request' }),
    /task_id/,
  );
  assert.throws(
    () => bridge.postIntent({
      type: 'host.open_vscode',
      path: 'C:\\workspace',
      command: 'Remove-Item',
    }),
    /unknown field/,
  );
  assert.throws(
    () => bridge.postIntent({ type: 'chat.publish', content: 'x'.repeat(70_000) }),
    /too large/,
  );
});

test('HostBridge rejects an accessor without invoking it', () => {
  const forwarded = [];
  let typeReads = 0;
  const intent = { content: 'Message stable' };
  Object.defineProperty(intent, 'type', {
    enumerable: true,
    get() {
      typeReads += 1;
      return typeReads === 3 ? 'registry.write.raw' : 'chat.publish';
    },
  });
  const bridge = new HostBridge((value) => forwarded.push(value));

  assert.throws(() => bridge.postIntent(intent), /accessor/);

  assert.equal(typeReads, 0);
  assert.deepEqual(forwarded, []);
});

test('HostBridge rejects nested accessors and toJSON without invoking callbacks', () => {
  let accessorCalls = 0;
  let toJsonCalls = 0;
  const withAccessor = {};
  Object.defineProperty(withAccessor, 'secret', {
    enumerable: true,
    get() {
      accessorCalls += 1;
      return 'never';
    },
    set() {
      accessorCalls += 1;
    },
  });
  const withToJson = {
    toJSON() {
      toJsonCalls += 1;
      return {};
    },
  };
  const bridge = new HostBridge(() => assert.fail('must not forward'));

  assert.throws(
    () => bridge.postIntent({
      type: 'action.preview',
      action: 'service.health',
      parameters: { nested: withAccessor },
    }),
    /accessor/,
  );
  assert.throws(
    () => bridge.postIntent({
      type: 'action.preview',
      action: 'service.health',
      parameters: { nested: withToJson },
    }),
    /toJSON/,
  );
  assert.equal(accessorCalls, 0);
  assert.equal(toJsonCalls, 0);
});

test('HostBridge rejects inherited Object and Array toJSON without invoking them', () => {
  const objectDescriptor = Object.getOwnPropertyDescriptor(
    Object.prototype,
    'toJSON',
  );
  const arrayDescriptor = Object.getOwnPropertyDescriptor(
    Array.prototype,
    'toJSON',
  );
  let objectCalls = 0;
  let arrayCalls = 0;
  let forwarded = 0;
  let objectError;
  let arrayError;
  const bridge = new HostBridge(() => {
    forwarded += 1;
  });

  try {
    Object.defineProperty(Object.prototype, 'toJSON', {
      configurable: true,
      value() {
        objectCalls += 1;
        return this;
      },
    });
    try {
      bridge.postIntent({ type: 'chat.publish', content: 'safe' });
    } catch (error) {
      objectError = error;
    }
    restoreDescriptor(Object.prototype, 'toJSON', objectDescriptor);

    Object.defineProperty(Array.prototype, 'toJSON', {
      configurable: true,
      value() {
        arrayCalls += 1;
        return this;
      },
    });
    try {
      bridge.postIntent({
        type: 'action.preview',
        action: 'service.health',
        parameters: { values: [1, 2] },
      });
    } catch (error) {
      arrayError = error;
    }
  } finally {
    restoreDescriptor(Object.prototype, 'toJSON', objectDescriptor);
    restoreDescriptor(Array.prototype, 'toJSON', arrayDescriptor);
  }

  assert.match(String(objectError), /inherited toJSON/);
  assert.match(String(arrayError), /inherited toJSON/);
  assert.equal(objectCalls, 0);
  assert.equal(arrayCalls, 0);
  assert.equal(forwarded, 0);
});

test('HostBridge dispatches a deeply cloned and recursively frozen intent', () => {
  const original = {
    type: 'action.preview',
    action: 'service.health',
    parameters: {
      nested: { values: [1, { state: 'safe' }] },
    },
  };
  let dispatched;
  let mutationError;
  const bridge = new HostBridge((intent) => {
    dispatched = intent;
    try {
      intent.parameters.nested.values[1].state = 'mutated';
    } catch (error) {
      mutationError = error;
    }
  });

  bridge.postIntent(original);

  assertDeepFrozen(dispatched);
  assert.notStrictEqual(dispatched, original);
  assert.notStrictEqual(dispatched.parameters, original.parameters);
  assert.notStrictEqual(
    dispatched.parameters.nested.values,
    original.parameters.nested.values,
  );
  assert.ok(mutationError instanceof TypeError);
  assert.equal(dispatched.parameters.nested.values[1].state, 'safe');
  original.parameters.nested.values[1].state = 'changed outside';
  assert.equal(dispatched.parameters.nested.values[1].state, 'safe');
});

test('createWebViewBridge delegates to chrome.webview.postMessage', () => {
  const posted = [];
  const bridge = createWebViewBridge({
    postMessage(intent) {
      posted.push(intent);
    },
  });

  bridge.postIntent({ type: 'task.retry.request', task_id: 'task-2' });

  assert.deepEqual(posted, [
    { type: 'task.retry.request', task_id: 'task-2' },
  ]);
});

test('app orchestrates the client and exposes connection state without business actions', async () => {
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([message(1)]),
    socketFactory: sockets.factory,
  });
  const app = createApp({ client });
  const statuses = [];
  const unsubscribe = app.subscribe((snapshot) => {
    statuses.push(snapshot.connectionStatus);
  });

  await app.start(0);
  sockets.sockets[0].onopen?.();

  assert.equal(app.snapshot().connectionStatus, 'connected');
  assert.deepEqual(
    app.snapshot().state.messages.map((item) => item.global_offset),
    [1],
  );
  assert.ok(statuses.includes('replaying'));
  assert.ok(statuses.includes('connected'));
  unsubscribe();
  app.stop();
  assert.equal(app.snapshot().connectionStatus, 'stopped');
});

test('app isolates subscriber failures from connection lifecycle', async () => {
  const scheduler = fakeScheduler();
  const sockets = fakeSockets([]);
  const client = new CollabClient({
    fetch: async () => response([]),
    socketFactory: sockets.factory,
    setTimeout: scheduler.setTimeout,
    clearTimeout: scheduler.clearTimeout,
    onStatus() {
      throw new Error('previous observer failed');
    },
  });
  const app = createApp({ client });
  const observed = [];
  app.subscribe((snapshot) => {
    if (snapshot.connectionStatus !== 'idle') throw new Error('view failed');
  });
  app.subscribe((snapshot) => observed.push(snapshot.connectionStatus));

  await app.start(0);

  assert.equal(sockets.sockets.length, 1);
  assert.deepEqual(scheduler.delays, []);
  assert.ok(observed.includes('replaying'));
  assert.ok(observed.includes('connecting'));
  app.stop();
});

function assertDeepFrozen(value, seen = new Set()) {
  if (value === null || typeof value !== 'object' || seen.has(value)) return;
  seen.add(value);
  assert.equal(Object.isFrozen(value), true);
  for (const nested of Object.values(value)) assertDeepFrozen(nested, seen);
}

function restoreDescriptor(target, name, descriptor) {
  if (descriptor) {
    Object.defineProperty(target, name, descriptor);
  } else {
    delete target[name];
  }
}

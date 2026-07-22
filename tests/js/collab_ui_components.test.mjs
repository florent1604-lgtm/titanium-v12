import assert from 'node:assert/strict';
import test from 'node:test';

import { HostBridge } from '../../collab_ui/host_bridge.mjs';
import { createState, reduce } from '../../collab_ui/state.mjs';
import { renderMessages } from '../../collab_ui/components/messages.mjs';
import { renderAgents } from '../../collab_ui/components/agents.mjs';
import {
  capabilityLabel,
  renderActions,
} from '../../collab_ui/components/actions.mjs';
import {
  renderFailures,
  retryIntent,
} from '../../collab_ui/components/failures.mjs';
import { mountCommandDeck } from '../../collab_ui/app.mjs';

class FakeElement {
  constructor(tagName, ownerDocument) {
    this.tagName = tagName.toUpperCase();
    this.ownerDocument = ownerDocument;
    this.children = [];
    this.attributes = new Map();
    this.listeners = new Map();
    this.className = '';
    this.disabled = false;
    this.readOnly = false;
    this.value = '';
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.selectionDirection = 'none';
    this._textContent = '';
  }

  set textContent(value) {
    this._textContent = String(value ?? '');
    this.children = [];
  }

  get textContent() {
    return this._textContent + this.children.map((child) => child.textContent).join('');
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  replaceChildren(...children) {
    this._textContent = '';
    this.children = children;
    for (const child of children) child.parentElement = this;
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) ?? [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  dispatch(type) {
    const event = {
      currentTarget: this,
      preventDefault() {},
    };
    return (this.listeners.get(type) ?? []).map((listener) => listener(event));
  }

  focus() {
    this.ownerDocument.activeElement = this;
  }

  setSelectionRange(start, end, direction = 'none') {
    this.selectionStart = start;
    this.selectionEnd = end;
    this.selectionDirection = direction;
  }
}

class FakeDocument {
  activeElement = null;

  createElement(tagName) {
    return new FakeElement(tagName, this);
  }
}

function root() {
  const document = new FakeDocument();
  return document.createElement('div');
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

function one(node, predicate) {
  const matches = descendants(node).filter(predicate);
  assert.equal(matches.length, 1);
  return matches[0];
}

function byAction(node, action) {
  return one(node, (item) => item.getAttribute('data-action') === action);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

async function settle(results) {
  await Promise.all(results.filter((value) => value instanceof Promise));
  await Promise.resolve();
}

function message(offset, overrides = {}) {
  return {
    message_id: `message-${offset}`,
    global_offset: offset,
    created_at: `2026-07-${String(offset).padStart(2, '0')}T10:00:00Z`,
    principal: 'codex',
    task_id: 'COMMAND_DECK',
    kind: 'review',
    content: `Compte rendu ${offset}`,
    ...overrides,
  };
}

function failure(overrides = {}) {
  return {
    task_id: 'task-1',
    attempt_id: 'attempt-1',
    reason_code: 'TEST_FAILED',
    evidence_ref: 'node --test',
    status: 'A_REVALIDER',
    created_at: '2026-07-20T10:00:00Z',
    ...overrides,
  };
}

test('retryIntent is pure and failure loading never emits it', () => {
  const item = failure();
  const snapshot = structuredClone(item);
  const state = reduce(createState(), {
    type: 'failures.loaded',
    failures: [item],
  });

  assert.deepEqual(state.pendingIntents, []);
  assert.deepEqual(retryIntent(item), {
    type: 'task.retry.request',
    task_id: 'task-1',
  });
  assert.deepEqual(item, snapshot);
});

test('message rendering uses state selectors and loads older messages only on click', () => {
  const target = root();
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [
      message(4, { principal: 'codex', task_id: 'UI_TASK_3' }),
      message(2, { principal: 'claude', content: 'Autre message' }),
    ],
  });
  const requested = [];

  renderMessages(target, {
    state,
    filters: { agent: 'codex', task: 'UI_TASK_3', type: 'review' },
    onLoadOlder: (offset) => requested.push(offset),
  });

  assert.match(target.textContent, /Compte rendu 4/);
  assert.doesNotMatch(target.textContent, /Autre message/);
  assert.deepEqual(requested, []);
  byAction(target, 'load-older').dispatch('click');
  assert.deepEqual(requested, [2]);
});

test('load older has a synchronous durable lock and releases it after settle', async () => {
  const target = root();
  const pending = deferred();
  const interaction = { pending: new Set(), errors: new Map() };
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(2)],
  });
  let calls = 0;
  let options;
  const rerender = () => renderMessages(target, options);
  options = {
    state,
    interaction,
    onInteractionChange: rerender,
    onLoadOlder() {
      calls += 1;
      return pending.promise;
    },
  };
  rerender();
  const original = byAction(target, 'load-older');

  const first = original.dispatch('click');
  const second = original.dispatch('click');

  assert.equal(calls, 1);
  assert.equal(byAction(target, 'load-older').disabled, true);
  pending.resolve([]);
  await settle([...first, ...second]);
  assert.equal(byAction(target, 'load-older').disabled, false);
});

test('load older disables its current button even without a rerender callback', async () => {
  const target = root();
  const pending = deferred();
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(2)],
  });
  renderMessages(target, {
    state,
    onLoadOlder: () => pending.promise,
  });
  const button = byAction(target, 'load-older');

  const result = button.dispatch('click');
  assert.equal(button.disabled, true);
  pending.resolve([]);
  await settle(result);
  assert.equal(button.disabled, false);
});

test('load older rejection is handled, sanitized, and releases pending', async () => {
  const target = root();
  const interaction = { pending: new Set(), errors: new Map() };
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(2)],
  });
  let options;
  const rerender = () => renderMessages(target, options);
  options = {
    state,
    interaction,
    onInteractionChange: rerender,
    onLoadOlder: () => Promise.reject(new Error('ADMIN_TOKEN=do-not-render')),
  };
  rerender();

  await settle(byAction(target, 'load-older').dispatch('click'));

  assert.match(target.textContent, /Chargement indisponible/);
  assert.doesNotMatch(target.textContent, /ADMIN_TOKEN|do-not-render/);
  assert.equal(byAction(target, 'load-older').disabled, false);
});

test('text filters commit after editing instead of rerendering on each keystroke', () => {
  const target = root();
  const updates = [];
  renderMessages(target, {
    state: createState(),
    onFilterChange: (filters) => updates.push(filters),
  });
  const search = one(target, (node) => node.name === 'text');
  search.value = 'verdict';

  search.dispatch('input');
  assert.deepEqual(updates, []);
  search.dispatch('change');
  assert.equal(updates.at(-1).text, 'verdict');
});

test('composer stays read-only without a real HostBridge', () => {
  const target = root();
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(1)],
  });

  renderMessages(target, { state, bridge: { postIntent() {} } });

  const composer = byAction(target, 'compose-message');
  const send = byAction(target, 'send-message');
  assert.equal(composer.disabled, true);
  assert.equal(composer.readOnly, true);
  assert.equal(composer.getAttribute('aria-disabled'), 'true');
  assert.equal(send.disabled, true);
});

test('composer forwards one allowlisted intent only after a manual click', () => {
  const target = root();
  const posted = [];
  const bridge = new HostBridge((intent) => posted.push(intent));

  renderMessages(target, { state: createState(), bridge });
  const composer = byAction(target, 'compose-message');
  composer.value = 'Verdict commun';
  assert.deepEqual(posted, []);

  byAction(target, 'send-message').dispatch('click');

  assert.deepEqual(posted, [
    { type: 'chat.publish', content: 'Verdict commun' },
  ]);
});

test('composer handles asynchronous HostBridge rejection without leaking details', async () => {
  const target = root();
  const interaction = { pending: new Set(), errors: new Map() };
  const bridge = new HostBridge(() => Promise.reject(new Error('secret payload')));
  let options;
  const rerender = () => renderMessages(target, options);
  options = {
    state: createState(),
    bridge,
    interaction,
    draft: 'Verdict commun',
    onInteractionChange: rerender,
  };
  rerender();

  await settle(byAction(target, 'send-message').dispatch('click'));

  assert.match(target.textContent, /Envoi indisponible/);
  assert.doesNotMatch(target.textContent, /secret payload/);
  assert.equal(byAction(target, 'send-message').disabled, false);
});

test('agent rendering treats supplied names as text', () => {
  const target = root();
  renderAgents(target, {
    agents: [{ code: 'CX', name: '<img src=x>', status: 'ready', role: 'audit' }],
  });

  assert.match(target.textContent, /<img src=x>/);
  assert.equal(descendants(target).some((node) => node.tagName === 'IMG'), false);
});

test('desktop guard has a real separator and never concatenates its warnings', () => {
  const target = root();
  renderAgents(target);

  assert.equal(descendants(target).some((node) => node.tagName === 'BR'), true);
  assert.doesNotMatch(target.textContent, /PAPER ONLYRÉEL INTERDIT/);
});

test('dock exposes the five exact capability states and UNKNOWN is unavailable', () => {
  assert.equal(capabilityLabel('AVAILABLE'), 'Disponible');
  assert.equal(capabilityLabel('VALIDATION_REQUIRED'), 'Validation requise');
  assert.equal(capabilityLabel('DOUBLE_SIGNATURE'), 'Double signature');
  assert.equal(capabilityLabel('BLOCKED'), 'Bloquée');
  assert.equal(capabilityLabel('UNKNOWN'), 'Indisponible');

  const target = root();
  const bridge = new HostBridge(() => {});
  renderActions(target, {
    bridge,
    capabilities: { openVscode: 'UNKNOWN', serviceHealth: 'AVAILABLE' },
  });

  const unknown = byAction(target, 'open-vscode');
  assert.equal(unknown.disabled, true);
  assert.equal(unknown.getAttribute('data-capability-state'), 'UNKNOWN');
  assert.equal(unknown.className.includes('is-available'), false);
  assert.equal(byAction(target, 'service-health').disabled, false);
});

test('dock actions only forward HostBridge intents after a manual click', () => {
  const target = root();
  const posted = [];
  const bridge = new HostBridge((intent) => posted.push(intent));
  renderActions(target, {
    bridge,
    capabilities: { serviceHealth: 'AVAILABLE' },
  });

  assert.deepEqual(posted, []);
  byAction(target, 'service-health').dispatch('click');
  assert.deepEqual(posted, [
    { type: 'action.preview', action: 'service.health', parameters: {} },
  ]);
});

test('dock catches synchronous HostBridge throws and shows only a safe error', async () => {
  const target = root();
  const interaction = { pending: new Set(), errors: new Map() };
  const bridge = new HostBridge(() => {
    throw new Error('X-Collab-Session=never-render');
  });
  let options;
  const rerender = () => renderActions(target, options);
  options = {
    bridge,
    capabilities: { serviceHealth: 'AVAILABLE' },
    interaction,
    onInteractionChange: rerender,
  };
  rerender();

  await settle(byAction(target, 'service-health').dispatch('click'));

  assert.match(target.textContent, /Action indisponible/);
  assert.doesNotMatch(target.textContent, /X-Collab-Session|never-render/);
  assert.equal(byAction(target, 'service-health').disabled, false);
});

test('failure view counts non-closed failures and retries only on click', () => {
  const target = root();
  const posted = [];
  const bridge = new HostBridge((intent) => posted.push(intent));
  const state = reduce(createState(), {
    type: 'failures.loaded',
    failures: [
      failure(),
      failure({ task_id: 'task-2', status: 'UNKNOWN' }),
      failure({ task_id: 'task-3', status: 'CLOSED' }),
    ],
  });

  renderFailures(target, { state, bridge });

  assert.equal(one(target, (node) => node.getAttribute('data-open-count') === '2').textContent, '2');
  assert.deepEqual(posted, []);
  byAction(target, 'retry-task-1').dispatch('click');
  assert.deepEqual(posted, [
    { type: 'task.retry.request', task_id: 'task-1' },
  ]);
});

test('failure view exposes an unavailable state without raw transport details', () => {
  const target = root();
  const state = reduce(createState(), { type: 'failures.failed' });

  renderFailures(target, { state });

  assert.match(target.textContent, /Échecs indisponibles/);
  assert.doesNotMatch(target.textContent, /401|X-Collab-Session|token/i);
});

test('retry has a per-task synchronous lock across rerenders and releases on rejection', async () => {
  const target = root();
  const pending = deferred();
  const interaction = { pending: new Set(), errors: new Map() };
  let posts = 0;
  const bridge = new HostBridge(() => {
    posts += 1;
    return pending.promise;
  });
  const state = reduce(createState(), {
    type: 'failures.loaded',
    failures: [failure()],
  });
  let options;
  const rerender = () => renderFailures(target, options);
  options = {
    state,
    bridge,
    interaction,
    onInteractionChange: rerender,
  };
  rerender();
  const original = byAction(target, 'retry-task-1');

  const first = original.dispatch('click');
  const second = original.dispatch('click');

  assert.equal(posts, 1);
  assert.equal(byAction(target, 'retry-task-1').disabled, true);
  pending.reject(new Error('private retry detail'));
  await settle([...first, ...second]);
  assert.match(target.textContent, /Nouvel essai indisponible/);
  assert.doesNotMatch(target.textContent, /private retry detail/);
  assert.equal(byAction(target, 'retry-task-1').disabled, false);
});

test('command deck mounts Conversation and Échecs à suivre as keyboard buttons', () => {
  const target = root();
  const app = {
    snapshot: () => ({ connectionStatus: 'idle', state: createState() }),
    subscribe(listener) {
      listener(this.snapshot());
      return () => {};
    },
    loadOlder() {},
  };

  mountCommandDeck({ root: target, app });

  const conversation = byAction(target, 'tab-conversation');
  const failures = byAction(target, 'tab-failures');
  assert.equal(conversation.tagName, 'BUTTON');
  assert.equal(conversation.getAttribute('aria-selected'), 'true');
  assert.equal(failures.textContent, 'Échecs à suivre');
  failures.dispatch('click');
  assert.equal(failures.getAttribute('aria-selected'), 'true');
  assert.match(target.textContent, /Aucun échec à suivre/);
});

test('realtime snapshots preserve composer draft, focus, and text selection', () => {
  const target = root();
  const bridge = new HostBridge(() => {});
  let current = { connectionStatus: 'connected', state: createState() };
  let subscriber;
  const app = {
    snapshot: () => current,
    subscribe(listener) {
      subscriber = listener;
      listener(current);
      return () => {};
    },
    loadOlder() {},
  };
  mountCommandDeck({ root: target, app, bridge });
  const composer = byAction(target, 'compose-message');
  composer.value = 'Brouillon non publié';
  composer.dispatch('input');
  composer.focus();
  composer.setSelectionRange(4, 12, 'forward');

  current = {
    connectionStatus: 'connected',
    state: reduce(createState(), {
      type: 'messages.loaded',
      messages: [message(8)],
    }),
  };
  subscriber(current);

  const restored = byAction(target, 'compose-message');
  assert.equal(restored.value, 'Brouillon non publié');
  assert.strictEqual(target.ownerDocument.activeElement, restored);
  assert.equal(restored.selectionStart, 4);
  assert.equal(restored.selectionEnd, 12);
  assert.equal(restored.selectionDirection, 'forward');
});

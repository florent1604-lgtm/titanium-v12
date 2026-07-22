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
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

class FakeDocument {
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

test('agent rendering treats supplied names as text', () => {
  const target = root();
  renderAgents(target, {
    agents: [{ code: 'CX', name: '<img src=x>', status: 'ready', role: 'audit' }],
  });

  assert.match(target.textContent, /<img src=x>/);
  assert.equal(descendants(target).some((node) => node.tagName === 'IMG'), false);
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

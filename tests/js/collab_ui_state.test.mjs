import assert from 'node:assert/strict';
import test from 'node:test';

import {
  createState,
  reduce,
  selectFailures,
  selectMessages,
} from '../../collab_ui/state.mjs';

function message(globalOffset, principal, overrides = {}) {
  return {
    message_id: `message-${globalOffset}`,
    global_offset: globalOffset,
    created_at: `2026-07-${String(globalOffset).padStart(2, '0')}T10:00:00Z`,
    principal,
    task_id: 'COMMAND_DECK',
    kind: 'review',
    content: `Compte rendu ${globalOffset}`,
    ...overrides,
  };
}

function failure(taskId, overrides = {}) {
  return {
    task_id: taskId,
    attempt_id: `attempt-${taskId}`,
    reason_code: 'TEST_FAILED',
    evidence_ref: `node --test ${taskId}`,
    status: 'A_REVALIDER',
    created_at: '2026-07-20T10:00:00Z',
    ...overrides,
  };
}

test('createState preserves UNKNOWN as an explicit initial state', () => {
  assert.deepEqual(createState(), {
    messages: [],
    failures: [],
    pendingIntents: [],
    loadState: { messages: 'UNKNOWN', failures: 'UNKNOWN' },
  });
});

test('loading failures never creates a pending intent', () => {
  const state = reduce(createState(), {
    type: 'failures.loaded',
    failures: [failure('task-1')],
  });

  assert.deepEqual(state.pendingIntents, []);
});

test('filters by agent and keeps global offset order', () => {
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(3, 'codex'), message(1, 'claude')],
  });

  assert.deepEqual(
    selectMessages(state, { principal: 'codex' }).map(
      (item) => item.global_offset,
    ),
    [3],
  );
  assert.deepEqual(
    selectMessages(state, {}).map((item) => item.global_offset),
    [1, 3],
  );
});

test('deduplicates message replays by message_id without mutating either input', () => {
  const initial = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(2, 'hermes', { content: 'Version initiale' })],
  });
  const replay = [
    message(2, 'hermes', { content: 'Version initiale' }),
    message(4, 'florent'),
  ];
  const initialSnapshot = structuredClone(initial);
  const replaySnapshot = structuredClone(replay);

  const next = reduce(initial, { type: 'messages.loaded', messages: replay });

  assert.deepEqual(initial, initialSnapshot);
  assert.deepEqual(replay, replaySnapshot);
  assert.notStrictEqual(next, initial);
  assert.notStrictEqual(next.messages, initial.messages);
  assert.deepEqual(
    next.messages.map((item) => item.message_id),
    ['message-2', 'message-4'],
  );
});

test('combines normalized text, agent, task, type, and inclusive period filters', () => {
  const wanted = message(8, 'codex', {
    task_id: 'UI_TASK_1',
    kind: 'review',
    content: 'Vérification clôturée — aucun chemin réel.',
  });
  const state = reduce(createState(), {
    type: 'messages.loaded',
    messages: [
      wanted,
      message(7, 'codex', { task_id: 'UI_TASK_1', kind: 'status' }),
      message(9, 'claude', { task_id: 'UI_TASK_1', kind: 'review' }),
      message(10, 'codex', { task_id: 'AUTRE', kind: 'review' }),
    ],
  });
  const sourceSnapshot = structuredClone(state.messages);

  const selected = selectMessages(state, {
    text: 'verification CLOTUREE',
    agent: 'CODEX',
    task: 'ui_task_1',
    type: 'REVIEW',
    period: {
      from: '2026-07-08T10:00:00Z',
      to: '2026-07-08T10:00:00Z',
    },
  });

  assert.deepEqual(selected, [wanted]);
  assert.deepEqual(state.messages, sourceSnapshot);
  assert.notStrictEqual(selected, state.messages);
});

test('loads and filters failures while keeping explicit UNKNOWN distinct from missing', () => {
  const unknown = failure('UI_TASK_1', {
    attempt_id: 'attempt-unknown',
    status: 'UNKNOWN',
    evidence_ref: 'Échec réseau constaté',
  });
  const missing = failure('UI_TASK_2', {
    attempt_id: 'attempt-missing',
  });
  delete missing.status;
  const state = reduce(createState(), {
    type: 'failures.loaded',
    failures: [missing, unknown],
  });
  const sourceSnapshot = structuredClone(state.failures);

  assert.equal(state.loadState.failures, 'READY');
  assert.deepEqual(
    selectFailures(state, {
      text: 'echec reseau',
      task: 'ui_task_1',
      type: 'test_failed',
      status: 'unknown',
      period: { from: '2026-07-20', to: '2026-07-20T23:59:59Z' },
    }),
    [unknown],
  );
  assert.deepEqual(selectFailures(state, { status: 'UNKNOWN' }), [unknown]);
  assert.deepEqual(state.failures, sourceSnapshot);
});

test('marks the failure feed unavailable without exposing an error payload', () => {
  const initial = reduce(createState(), {
    type: 'messages.loaded',
    messages: [message(3, 'codex')],
  });

  const state = reduce(initial, { type: 'failures.failed' });

  assert.equal(state.loadState.failures, 'UNAVAILABLE');
  assert.deepEqual(state.messages, initial.messages);
  assert.equal(JSON.stringify(state).includes('secret'), false);
});

test('returns the same state for an unknown reducer event', () => {
  const state = createState();
  assert.strictEqual(reduce(state, { type: 'outside.task-1' }), state);
});

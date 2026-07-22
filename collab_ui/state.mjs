const UNKNOWN = 'UNKNOWN';
const READY = 'READY';

export function createState() {
  return {
    messages: [],
    failures: [],
    loadState: {
      messages: UNKNOWN,
      failures: UNKNOWN,
    },
  };
}

export function reduce(state, event) {
  if (event?.type === 'messages.loaded') {
    return {
      ...state,
      messages: mergeMessages(state.messages, event.messages),
      loadState: { ...state.loadState, messages: READY },
    };
  }

  if (event?.type === 'failures.loaded') {
    return {
      ...state,
      failures: copyRecords(event.failures),
      loadState: { ...state.loadState, failures: READY },
    };
  }

  return state;
}

export function selectMessages(state, filter = {}) {
  return selectRecords(state.messages, filter);
}

export function selectFailures(state, filter = {}) {
  return selectRecords(state.failures, filter);
}

function mergeMessages(current, incoming) {
  const withoutId = [];
  const byId = new Map();

  for (const item of [...copyRecords(current), ...copyRecords(incoming)]) {
    if (item.message_id === undefined || item.message_id === null) {
      withoutId.push(item);
      continue;
    }

    const previous = byId.get(item.message_id);
    if (
      previous === undefined ||
      offsetOf(item) >= offsetOf(previous)
    ) {
      byId.set(item.message_id, item);
    }
  }

  return [...byId.values(), ...withoutId].sort(
    (left, right) => offsetOf(left) - offsetOf(right),
  );
}

function copyRecords(records) {
  if (!Array.isArray(records)) return [];
  return records.map((record) => ({ ...record }));
}

function offsetOf(record) {
  const offset = Number(record.global_offset);
  return Number.isFinite(offset) ? offset : Number.POSITIVE_INFINITY;
}

function selectRecords(records, filter) {
  const source = Array.isArray(records) ? records : [];
  const text = normalized(filter.text ?? filter.query ?? '');
  const agent = filter.agent ?? filter.principal;
  const task = filter.task ?? filter.task_id;
  const type = filter.type ?? filter.kind;

  return source.filter((record) => {
    if (text && !searchText(record).includes(text)) return false;
    if (!same(record.principal ?? record.agent ?? record.owner, agent)) {
      return false;
    }
    if (!same(record.task_id ?? record.task, task)) return false;
    if (!same(record.kind ?? record.type ?? record.reason_code, type)) {
      return false;
    }
    if (!sameStatus(record, filter.status)) return false;
    return isWithinPeriod(record.created_at, filter.period);
  });
}

function same(value, expected) {
  if (expected === undefined || expected === null || expected === '') return true;
  return normalized(value) === normalized(expected);
}

function sameStatus(record, expected) {
  if (expected === undefined || expected === null || expected === '') return true;
  if (!Object.hasOwn(record, 'status')) return false;
  return normalized(record.status) === normalized(expected);
}

function searchText(record) {
  return normalized(
    [
      record.content,
      record.principal,
      record.target,
      record.kind,
      record.task_id,
      record.reason_code,
      record.evidence_ref,
      record.status,
      record.attempt_id,
    ]
      .filter((value) => value !== undefined && value !== null)
      .join(' '),
  );
}

function normalized(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLocaleLowerCase('fr-FR')
    .replace(/\s+/g, ' ')
    .trim();
}

function isWithinPeriod(createdAt, period) {
  if (!period) return true;

  const timestamp = Date.parse(createdAt);
  if (!Number.isFinite(timestamp)) return false;

  const from = parseBoundary(period.from ?? period.start);
  const to = parseBoundary(period.to ?? period.end);
  if (from !== null && timestamp < from) return false;
  if (to !== null && timestamp > to) return false;
  return true;
}

function parseBoundary(value) {
  if (value === undefined || value === null || value === '') return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : Number.NaN;
}

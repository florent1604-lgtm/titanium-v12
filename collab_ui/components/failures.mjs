import { HostBridge } from '../host_bridge.mjs';
import { selectFailures } from '../state.mjs';

const CLOSED_STATUSES = new Set(['CLOSED', 'CLOTURE', 'CLOTUREE', 'DONE', 'RESOLVED', 'SUCCESS', 'VALIDATED']);

export function retryIntent(failure) {
  const taskId = failure?.task_id;
  if (typeof taskId !== 'string' || taskId.trim() === '') {
    throw new TypeError('A failure task_id is required');
  }
  return { type: 'task.retry.request', task_id: taskId };
}

export function renderFailures(root, options = {}) {
  const document = documentOf(root);
  const state = options.state ?? { failures: [] };
  const filters = options.filters ?? {};
  const records = selectFailures(state, selectorFilters(filters));
  const heading = element(document, 'div', 'failure-title-row');
  const title = element(document, 'h2');
  title.textContent = 'Échecs à suivre';
  const count = element(document, 'span', 'failure-count');
  const openCount = (state.failures ?? []).filter(isOpenFailure).length;
  count.textContent = String(openCount);
  count.setAttribute('data-open-count', String(openCount));
  count.setAttribute('aria-label', `${openCount} échec${openCount === 1 ? '' : 's'} non clos`);
  heading.replaceChildren(title, count);

  const filterBar = createFilterBar(document, state.failures ?? [], filters, options.onFilterChange);
  const ledger = element(document, 'div', 'failure-ledger');
  const rows = records.map((failure) => createFailure(document, failure, options.bridge));
  if (rows.length === 0) {
    const empty = element(document, 'p', 'empty-state');
    empty.textContent = 'Aucun échec à suivre.';
    rows.push(empty);
  }
  ledger.replaceChildren(...rows);
  root.replaceChildren(heading, filterBar, ledger);
  return root;
}

function createFailure(document, failure, bridge) {
  const row = element(document, 'article', `failure-row${isOpenFailure(failure) ? ' is-open' : ' is-closed'}`);
  const header = element(document, 'header');
  const reason = element(document, 'strong');
  reason.textContent = text(failure.reason_code ?? failure.kind ?? failure.type, 'UNKNOWN');
  const status = element(document, 'span', `failure-status status-${statusOf(failure).toLocaleLowerCase('fr-FR')}`);
  status.textContent = statusOf(failure);
  header.replaceChildren(reason, status);
  const task = element(document, 'p');
  task.textContent = `${text(failure.task_id ?? failure.task, 'Tâche inconnue')} · ${text(failure.attempt_id, 'Tentative inconnue')}`;
  const evidence = element(document, 'small');
  evidence.textContent = text(failure.evidence_ref, 'Aucune preuve jointe');

  const children = [header, task, evidence];
  if (isOpenFailure(failure)) {
    const retry = element(document, 'button', 'retry-action');
    retry.type = 'button';
    retry.textContent = 'Demander un nouvel essai';
    retry.setAttribute('data-action', `retry-${text(failure.task_id, 'unknown')}`);
    const enabled = bridge instanceof HostBridge;
    retry.disabled = !enabled;
    retry.setAttribute('aria-disabled', String(!enabled));
    if (enabled) retry.addEventListener('click', () => bridge.postIntent(retryIntent(failure)));
    children.push(retry);
  }
  row.replaceChildren(...children);
  return row;
}

function createFilterBar(document, records, filters, onFilterChange) {
  const bar = element(document, 'div', 'filters failure-filters');
  bar.setAttribute('role', 'search');
  bar.setAttribute('aria-label', 'Filtrer les échecs');
  const update = typeof onFilterChange === 'function' ? onFilterChange : () => {};
  const definitions = [
    ['Texte', 'search', 'text'],
    ['Agent', 'text', 'agent'],
    ['Tâche', 'text', 'task'],
    ['Type', 'text', 'type'],
    ['Depuis', 'date', 'period'],
  ];
  const controls = definitions.map(([labelText, type, name]) => {
    const label = element(document, 'label', `filter${name === 'text' ? ' filter-search' : ''}`);
    const caption = element(document, 'span');
    caption.textContent = labelText;
    const input = element(document, 'input');
    input.type = type;
    input.name = name;
    input.value = name === 'period' ? periodValue(filters.period) : String(filters[name] ?? '');
    input.addEventListener('change', (event) => update({ ...filters, [name]: event.currentTarget.value }));
    label.replaceChildren(caption, input);
    return label;
  });
  bar.replaceChildren(...controls);
  return bar;
}

function isOpenFailure(failure) {
  return !CLOSED_STATUSES.has(normalizeStatus(failure?.status));
}

function statusOf(failure) {
  const status = normalizeStatus(failure?.status);
  return status === '' ? 'UNKNOWN' : status;
}

function normalizeStatus(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/\p{M}/gu, '')
    .toLocaleUpperCase('fr-FR')
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function selectorFilters(filters) {
  const period = filters.period;
  return {
    ...filters,
    period: typeof period === 'string' && period !== '' ? { from: period } : period,
  };
}

function periodValue(period) {
  if (typeof period === 'string') return period;
  if (period && typeof period === 'object') return String(period.from ?? period.start ?? '').slice(0, 10);
  return '';
}

function text(value, fallback) {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function element(document, tagName, className = '') {
  const node = document.createElement(tagName);
  node.className = className;
  return node;
}

function documentOf(root) {
  if (!root?.ownerDocument || typeof root.ownerDocument.createElement !== 'function') {
    throw new TypeError('A DOM root is required');
  }
  return root.ownerDocument;
}

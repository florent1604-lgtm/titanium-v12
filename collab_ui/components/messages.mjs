import { HostBridge } from '../host_bridge.mjs';
import { selectMessages } from '../state.mjs';

export function renderMessages(root, options = {}) {
  const document = documentOf(root);
  const state = options.state ?? { messages: [] };
  const filters = options.filters ?? {};
  const records = selectMessages(state, selectorFilters(filters));
  const filterBar = createFilterBar(document, state.messages ?? [], filters, options.onFilterChange);
  const history = createHistoryControl(document, state.messages ?? [], options.onLoadOlder);
  const log = element(document, 'div', 'message-log');
  log.setAttribute('aria-label', 'Messages du journal');

  const rows = records.map((record) => createMessage(document, record));
  if (rows.length === 0) {
    const empty = element(document, 'p', 'empty-state');
    empty.textContent = 'Aucun message ne correspond aux filtres.';
    rows.push(empty);
  }
  log.replaceChildren(...rows);

  const composer = createComposer(document, options.bridge);
  root.replaceChildren(filterBar, history, log, composer);
  return root;
}

function createFilterBar(document, records, filters, onFilterChange) {
  const bar = element(document, 'div', 'filters');
  bar.setAttribute('role', 'search');
  bar.setAttribute('aria-label', 'Filtrer le journal');
  const update = typeof onFilterChange === 'function' ? onFilterChange : () => {};

  const text = inputFilter(document, 'Texte', 'search', 'text', filters.text ?? '', (value) => {
    update({ ...filters, text: value });
  });
  text.className = 'filter filter-search';
  const agent = selectFilter(
    document,
    'Agent',
    'agent',
    filters.agent ?? '',
    unique(records.map((record) => record.principal ?? record.agent ?? record.owner)),
    (value) => update({ ...filters, agent: value }),
  );
  const task = inputFilter(document, 'Tâche', 'text', 'task', filters.task ?? '', (value) => {
    update({ ...filters, task: value });
  });
  const type = selectFilter(
    document,
    'Type',
    'type',
    filters.type ?? '',
    unique(records.map((record) => record.kind ?? record.type ?? record.reason_code)),
    (value) => update({ ...filters, type: value }),
  );
  const period = inputFilter(
    document,
    'Depuis',
    'date',
    'period',
    periodValue(filters.period),
    (value) => update({ ...filters, period: value }),
  );

  bar.replaceChildren(text, agent, task, type, period);
  return bar;
}

function createHistoryControl(document, records, onLoadOlder) {
  const row = element(document, 'div', 'history-control');
  const button = element(document, 'button', 'load-older');
  button.type = 'button';
  button.textContent = 'Charger les messages antérieurs';
  button.setAttribute('data-action', 'load-older');
  const offsets = records
    .map((record) => Number(record.global_offset))
    .filter((offset) => Number.isSafeInteger(offset) && offset >= 0);
  const earliest = offsets.length > 0 ? Math.min(...offsets) : null;
  const enabled = earliest !== null && typeof onLoadOlder === 'function';
  setEnabled(button, enabled);
  if (enabled) button.addEventListener('click', () => onLoadOlder(earliest));
  row.replaceChildren(button);
  return row;
}

function createMessage(document, record) {
  const article = element(document, 'article', `message message-${agentClass(record)}`);
  const header = element(document, 'header');
  const principal = element(document, 'span', 'message-agent');
  principal.textContent = `${display(record.principal ?? record.agent, 'Agent')} / ${display(record.kind ?? record.type, 'Message')}`;
  const meta = element(document, 'span', 'message-meta');
  meta.textContent = `${display(record.created_at, 'Date inconnue')} · #${display(record.global_offset, '—')}`;
  header.replaceChildren(principal, meta);

  const content = element(document, 'p');
  content.textContent = display(record.content, 'Message sans contenu');
  const footer = element(document, 'footer');
  const task = element(document, 'span');
  task.textContent = display(record.task_id ?? record.task, 'SANS TÂCHE');
  const target = element(document, 'span');
  target.textContent = display(record.target, 'INTERNE');
  footer.replaceChildren(task, target);
  article.replaceChildren(header, content, footer);
  return article;
}

function createComposer(document, bridge) {
  const wrapper = element(document, 'div', 'composer');
  wrapper.setAttribute('aria-label', 'Composer un message');
  const label = element(document, 'label');
  label.textContent = 'Message ou commande';
  label.setAttribute('for', 'message-input');
  const textarea = element(document, 'textarea');
  textarea.id = 'message-input';
  textarea.rows = 2;
  textarea.setAttribute('data-action', 'compose-message');
  textarea.setAttribute('placeholder', 'Écrire à l’équipe ou /commander…');
  const send = element(document, 'button');
  send.type = 'button';
  send.textContent = 'Envoyer';
  send.setAttribute('data-action', 'send-message');

  const available = bridge instanceof HostBridge;
  setEnabled(textarea, available);
  textarea.readOnly = !available;
  setEnabled(send, available);
  if (available) {
    send.addEventListener('click', () => {
      const content = String(textarea.value ?? '').trim();
      if (content.length === 0) return;
      bridge.postIntent({ type: 'chat.publish', content });
    });
  }
  wrapper.replaceChildren(label, textarea, send);
  return wrapper;
}

function inputFilter(document, labelText, type, name, value, onChange) {
  const label = element(document, 'label', 'filter');
  const text = element(document, 'span');
  text.textContent = labelText;
  const input = element(document, 'input');
  input.type = type;
  input.name = name;
  input.value = value;
  input.addEventListener('change', (event) => onChange(event.currentTarget.value));
  label.replaceChildren(text, input);
  return label;
}

function selectFilter(document, labelText, name, value, values, onChange) {
  const label = element(document, 'label', 'filter');
  const text = element(document, 'span');
  text.textContent = labelText;
  const select = element(document, 'select');
  select.name = name;
  select.value = value;
  const all = element(document, 'option');
  all.value = '';
  all.textContent = 'Tous';
  const options = values.map((item) => {
    const option = element(document, 'option');
    option.value = item;
    option.textContent = item;
    return option;
  });
  select.replaceChildren(all, ...options);
  select.value = value;
  select.addEventListener('change', (event) => onChange(event.currentTarget.value));
  label.replaceChildren(text, select);
  return label;
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

function unique(values) {
  return [...new Set(values.filter((value) => value !== undefined && value !== null && value !== '').map(String))].sort();
}

function agentClass(record) {
  return String(record.principal ?? record.agent ?? 'unknown')
    .toLocaleLowerCase('fr-FR')
    .replace(/[^a-z0-9_-]/g, '');
}

function display(value, fallback) {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function setEnabled(control, enabled) {
  control.disabled = !enabled;
  control.setAttribute('aria-disabled', String(!enabled));
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

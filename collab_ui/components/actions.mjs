import { HostBridge } from '../host_bridge.mjs';

const CAPABILITY_LABELS = Object.freeze({
  AVAILABLE: 'Disponible',
  VALIDATION_REQUIRED: 'Validation requise',
  DOUBLE_SIGNATURE: 'Double signature',
  BLOCKED: 'Bloquée',
  UNKNOWN: 'Indisponible',
});

const ACTIONS = Object.freeze([
  Object.freeze({
    key: 'openVscode',
    action: 'open-vscode',
    label: 'Ouvrir VS Code',
    intent: Object.freeze({ type: 'host.open_vscode' }),
  }),
  Object.freeze({
    key: 'serviceHealth',
    action: 'service-health',
    label: 'Santé services',
    intent: Object.freeze({ type: 'action.preview', action: 'service.health', parameters: Object.freeze({}) }),
  }),
  Object.freeze({
    key: 'demoCommand',
    action: 'prepare-demo',
    label: 'Préparer commande DEMO',
    intent: Object.freeze({ type: 'action.preview', action: 'demo.command.prepare', parameters: Object.freeze({}) }),
  }),
  Object.freeze({
    key: 'gitnexusSigned',
    action: 'prepare-gitnexus',
    label: 'GitNexus signé',
    intent: Object.freeze({ type: 'action.preview', action: 'gitnexus.signed.prepare', parameters: Object.freeze({}) }),
  }),
]);

export function capabilityLabel(status) {
  return CAPABILITY_LABELS[normalizeStatus(status)];
}

export function renderActions(root, options = {}) {
  const document = documentOf(root);
  const bridge = options.bridge;
  const capabilities = options.capabilities ?? {};
  const heading = element(document, 'div', 'dock-heading');
  const eyebrow = element(document, 'p', 'eyebrow');
  eyebrow.textContent = 'Intentions contrôlées';
  const title = element(document, 'h2');
  title.textContent = 'Actions';
  heading.replaceChildren(eyebrow, title);

  const rows = ACTIONS.map((definition) => createAction(document, definition, capabilities, bridge));
  const note = element(document, 'p', 'dock-note');
  note.textContent = bridge instanceof HostBridge
    ? 'Chaque action émet une intention traçable. Aucun effet direct n’est exécuté par cette interface.'
    : 'Lecture seule : HostBridge allowlisté indisponible.';
  root.replaceChildren(heading, ...rows, note);
  return root;
}

function createAction(document, definition, capabilities, bridge) {
  const status = normalizeStatus(capabilities[definition.key]);
  const permitted = status === 'AVAILABLE' || status === 'VALIDATION_REQUIRED' || status === 'DOUBLE_SIGNATURE';
  const enabled = bridge instanceof HostBridge && permitted;
  const button = element(document, 'button', `dock-action capability-${status.toLocaleLowerCase('fr-FR')}${status === 'AVAILABLE' ? ' is-available' : ''}`);
  button.type = 'button';
  button.setAttribute('data-action', definition.action);
  button.setAttribute('data-capability-state', status);
  button.disabled = !enabled;
  button.setAttribute('aria-disabled', String(!enabled));
  const label = element(document, 'span');
  label.textContent = definition.label;
  const state = element(document, 'small');
  state.textContent = capabilityLabel(status);
  button.replaceChildren(label, state);
  if (enabled) button.addEventListener('click', () => bridge.postIntent(definition.intent));
  return button;
}

function normalizeStatus(status) {
  const normalized = String(status ?? 'UNKNOWN').toLocaleUpperCase('fr-FR');
  return Object.hasOwn(CAPABILITY_LABELS, normalized) ? normalized : 'UNKNOWN';
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

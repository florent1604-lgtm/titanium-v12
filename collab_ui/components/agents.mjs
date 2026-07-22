const DEFAULT_AGENTS = Object.freeze([
  Object.freeze({ code: 'HM', name: 'Hermes', status: 'online', role: 'analyse' }),
  Object.freeze({ code: 'CL', name: 'Claude', status: 'ready', role: 'revue' }),
  Object.freeze({ code: 'CX', name: 'Codex', status: 'ready', role: 'red-team' }),
  Object.freeze({ code: 'FL', name: 'Florent', status: 'arbitre', role: 'Windows', human: true }),
]);

export function renderAgents(root, options = {}) {
  const document = documentOf(root);
  const heading = element(document, 'h2', 'rail-heading');
  heading.textContent = 'Agents';
  const list = element(document, 'ol', 'agent-list');
  const agents = Array.isArray(options.agents) ? options.agents : DEFAULT_AGENTS;
  list.replaceChildren(...agents.map((agent) => createAgent(document, agent)));

  const guard = element(document, 'p', 'rail-guard');
  const paper = element(document, 'span');
  paper.textContent = 'PAPER ONLY';
  const real = element(document, 'span');
  real.textContent = 'RÉEL INTERDIT';
  guard.replaceChildren(paper, real);
  root.replaceChildren(heading, list, guard);
  return root;
}

function createAgent(document, agent) {
  const row = element(document, 'li', `agent-row${agent?.human === true ? ' is-human' : ''}`);
  const code = element(document, 'span', 'agent-code');
  code.textContent = text(agent?.code, '—');
  const identity = element(document, 'span');
  const name = element(document, 'strong');
  name.textContent = text(agent?.name, 'Agent inconnu');
  const status = element(document, 'small');
  status.textContent = `${text(agent?.status, 'UNKNOWN')} · ${text(agent?.role, 'rôle inconnu')}`;
  identity.replaceChildren(name, status);
  row.replaceChildren(code, identity);
  return row;
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

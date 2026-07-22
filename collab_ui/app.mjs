import { CollabClient } from './api.mjs';
import { renderActions } from './components/actions.mjs';
import { renderAgents } from './components/agents.mjs';
import { renderFailures } from './components/failures.mjs';
import { renderMessages } from './components/messages.mjs';
import { createWebViewBridge } from './host_bridge.mjs';
import { createInteractionState } from './components/interaction.mjs';

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

  async function loadFailures() {
    try {
      return await client.loadFailures();
    } finally {
      notify();
    }
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

  return Object.freeze({ loadFailures, loadOlder, snapshot, start, stop, subscribe });
}

export function mountCommandDeck(options = {}) {
  const root = options.root;
  const document = root?.ownerDocument;
  const app = options.app ?? createApp(options);
  if (!document || typeof document.createElement !== 'function') {
    throw new TypeError('A DOM root is required');
  }
  if (!app || typeof app.snapshot !== 'function' || typeof app.subscribe !== 'function') {
    throw new TypeError('A command deck app is required');
  }

  let activeTab = 'conversation';
  let filters = {};
  let composerDraft = '';
  let snapshot = app.snapshot();
  const interaction = createInteractionState();

  root.className = 'workspace';
  const agentRail = element(document, 'aside', 'operator-rail');
  agentRail.setAttribute('aria-label', 'Agents');
  renderAgents(agentRail, { agents: options.agents });

  const center = element(document, 'section', 'conversation');
  center.setAttribute('aria-label', 'Journal de collaboration');
  const activity = element(document, 'div', 'activity-strip');
  const activityLabel = element(document, 'span', 'activity-label');
  activityLabel.textContent = 'Flux durable';
  const connection = element(document, 'span', 'connection-status');
  const offset = element(document, 'span', 'offset');
  activity.replaceChildren(activityLabel, connection, offset);

  const tabList = element(document, 'div', 'view-tabs');
  tabList.setAttribute('role', 'tablist');
  tabList.setAttribute('aria-label', 'Vues du journal');
  const conversationTab = tabButton(document, 'Conversation', 'tab-conversation');
  const failuresTab = tabButton(document, 'Échecs à suivre', 'tab-failures');
  tabList.replaceChildren(conversationTab, failuresTab);
  const view = element(document, 'div', 'view-panel');
  view.setAttribute('role', 'tabpanel');
  center.replaceChildren(activity, tabList, view);

  const dock = element(document, 'aside', 'action-dock');
  dock.setAttribute('aria-label', 'Actions contrôlées');
  renderDock();
  root.replaceChildren(agentRail, center, dock);

  function renderView() {
    const preserved = captureInteraction(document, view);
    connection.textContent = connectionLabel(snapshot.connectionStatus);
    connection.setAttribute('data-connection-state', String(snapshot.connectionStatus ?? 'UNKNOWN').toLocaleUpperCase('fr-FR'));
    const offsets = (snapshot.state?.messages ?? [])
      .map((record) => Number(record.global_offset))
      .filter((value) => Number.isSafeInteger(value) && value >= 0);
    offset.textContent = `OFFSET / ${offsets.length > 0 ? Math.max(...offsets) : '—'}`;
    const conversationActive = activeTab === 'conversation';
    selectTab(conversationTab, conversationActive);
    selectTab(failuresTab, !conversationActive);
    view.setAttribute('aria-labelledby', conversationActive ? 'tab-conversation' : 'tab-failures');

    if (conversationActive) {
      renderMessages(view, {
        state: snapshot.state,
        filters,
        bridge: options.bridge,
        draft: composerDraft,
        onFilterChange: updateFilters,
        onDraftChange: (draft) => {
          composerDraft = draft;
        },
        interaction,
        onInteractionChange: renderView,
        onLoadOlder: (beforeOffset) => app.loadOlder(beforeOffset),
      });
    } else {
      renderFailures(view, {
        state: snapshot.state,
        filters,
        bridge: options.bridge,
        onFilterChange: updateFilters,
        interaction,
        onInteractionChange: renderView,
      });
    }
    restoreInteraction(view, preserved);
  }

  function renderDock() {
    renderActions(dock, {
      bridge: options.bridge,
      capabilities: options.capabilities,
      interaction,
      onInteractionChange: renderDock,
    });
  }

  function updateFilters(nextFilters) {
    filters = { ...nextFilters };
    renderView();
  }

  conversationTab.addEventListener('click', () => {
    activeTab = 'conversation';
    renderView();
  });
  failuresTab.addEventListener('click', () => {
    activeTab = 'failures';
    renderView();
  });

  const unsubscribe = app.subscribe((nextSnapshot) => {
    snapshot = nextSnapshot;
    renderView();
  });
  renderView();

  return Object.freeze({
    destroy() {
      unsubscribe();
    },
  });
}

export function bootCommandDeck(options = {}) {
  const document = options.document ?? globalThis.document;
  const root = options.root ?? document?.querySelector?.('[data-command-deck-root]');
  if (!root) return null;
  const app = options.app ?? createApp(options);
  const bridge = options.bridge ?? availableHostBridge(globalThis.chrome?.webview);
  const mounted = mountCommandDeck({ ...options, app, bridge, root });
  if (options.start !== false && typeof app.start === 'function') {
    const startup = Promise.resolve()
      .then(() => app.start(0))
      .catch(() => null)
      .then(() => {
        if (typeof app.loadFailures !== 'function') return null;
        return app.loadFailures();
      })
      .catch(() => null);
    void startup;
  }
  if (typeof globalThis.addEventListener === 'function' && typeof app.stop === 'function') {
    globalThis.addEventListener('beforeunload', () => app.stop(), { once: true });
  }
  return mounted;
}

function availableHostBridge(webview) {
  try {
    return createWebViewBridge(webview);
  } catch {
    return null;
  }
}

function tabButton(document, label, id) {
  const button = element(document, 'button', 'view-tab');
  button.id = id;
  button.type = 'button';
  button.textContent = label;
  button.setAttribute('role', 'tab');
  button.setAttribute('data-action', id);
  return button;
}

function selectTab(button, selected) {
  button.setAttribute('aria-selected', String(selected));
  button.setAttribute('tabindex', selected ? '0' : '-1');
  button.className = `view-tab${selected ? ' is-selected' : ''}`;
}

function connectionLabel(status) {
  const labels = {
    connected: 'CONNECTÉ',
    connecting: 'CONNEXION',
    replaying: 'RELECTURE',
    reconnecting: 'RECONNEXION',
    stopped: 'ARRÊTÉ',
    error: 'ERREUR',
    idle: 'UNKNOWN',
  };
  return labels[status] ?? 'UNKNOWN';
}

function element(document, tagName, className = '') {
  const node = document.createElement(tagName);
  node.className = className;
  return node;
}

function captureInteraction(document, root) {
  const active = document.activeElement;
  if (!active || !contains(root, active)) return null;
  const key = active.getAttribute?.('data-focus-key');
  if (!key) return null;
  return {
    key,
    value: typeof active.value === 'string' ? active.value : null,
    selectionStart: Number.isInteger(active.selectionStart) ? active.selectionStart : null,
    selectionEnd: Number.isInteger(active.selectionEnd) ? active.selectionEnd : null,
    selectionDirection: active.selectionDirection,
  };
}

function restoreInteraction(root, preserved) {
  if (!preserved) return;
  const control = findFocusKey(root, preserved.key);
  if (!control) return;
  if (preserved.value !== null) control.value = preserved.value;
  if (typeof control.focus === 'function') control.focus();
  if (
    preserved.selectionStart !== null &&
    preserved.selectionEnd !== null &&
    typeof control.setSelectionRange === 'function'
  ) {
    control.setSelectionRange(
      preserved.selectionStart,
      preserved.selectionEnd,
      preserved.selectionDirection,
    );
  }
}

function contains(root, target) {
  if (root === target) return true;
  for (const child of root.children ?? []) {
    if (contains(child, target)) return true;
  }
  return false;
}

function findFocusKey(root, key) {
  if (root.getAttribute?.('data-focus-key') === key) return root;
  for (const child of root.children ?? []) {
    const match = findFocusKey(child, key);
    if (match) return match;
  }
  return null;
}

if (typeof globalThis.document?.querySelector === 'function') {
  bootCommandDeck();
}

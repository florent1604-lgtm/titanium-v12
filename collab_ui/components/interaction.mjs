export function createInteractionState() {
  return { pending: new Set(), errors: new Map() };
}

export function isPending(interaction, key) {
  return interactionState(interaction).pending.has(key);
}

export function interactionError(interaction, key) {
  return interactionState(interaction).errors.get(key) ?? '';
}

export async function runGuardedInteraction(options) {
  const interaction = interactionState(options.interaction);
  const key = String(options.key);
  if (interaction.pending.has(key)) return false;

  interaction.pending.add(key);
  interaction.errors.delete(key);
  setControlsPending(options.controls, true);
  safelyNotify(options.onChange);
  try {
    await options.operation();
    return true;
  } catch {
    interaction.errors.set(key, String(options.errorMessage));
    return false;
  } finally {
    interaction.pending.delete(key);
    setControlsPending(options.controls, false);
    safelyNotify(options.onChange);
  }
}

function interactionState(value) {
  if (value?.pending instanceof Set && value?.errors instanceof Map) return value;
  return createInteractionState();
}

function safelyNotify(callback) {
  if (typeof callback !== 'function') return;
  try {
    callback();
  } catch {
    // Rendering failures never escape an interaction or expose host details.
  }
}

function setControlsPending(controls, pending) {
  for (const control of Array.isArray(controls) ? controls : []) {
    try {
      control.disabled = pending;
      control.setAttribute?.('aria-disabled', String(pending));
    } catch {
      // Detached controls are best-effort; the durable Set remains authoritative.
    }
  }
}

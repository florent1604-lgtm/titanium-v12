const MAX_INTENT_BYTES = 64 * 1024;

const SCHEMAS = Object.freeze({
  'chat.publish': {
    required: ['content'],
    optional: ['target', 'task_id', 'in_reply_to'],
  },
  'task.create': {
    required: ['title', 'owner', 'priority'],
    optional: [],
  },
  'task.retry.request': {
    required: ['task_id'],
    optional: [],
  },
  'action.preview': {
    required: ['action'],
    optional: ['parameters'],
  },
  'host.open_vscode': {
    required: [],
    optional: ['path'],
  },
});

export class HostBridge {
  constructor(postMessage) {
    if (typeof postMessage !== 'function') {
      throw new TypeError('HostBridge requires a postMessage function');
    }
    this.postMessage = postMessage;
  }

  postIntent(intent) {
    const safeIntent = validateIntent(intent);
    return this.postMessage(safeIntent);
  }
}

export function createWebViewBridge(webview) {
  if (!webview || typeof webview.postMessage !== 'function') {
    throw new TypeError('chrome.webview.postMessage is unavailable');
  }
  return new HostBridge((intent) => webview.postMessage(intent));
}

function validateIntent(intent) {
  if (!isPlainObject(intent)) throw new TypeError('Intent must be an object');
  const serialized = serializeIntent(intent);
  if (new TextEncoder().encode(serialized).byteLength > MAX_INTENT_BYTES) {
    throw new RangeError('Intent is too large');
  }
  const safeIntent = JSON.parse(serialized);
  if (!isPlainObject(safeIntent)) throw new TypeError('Intent must be an object');
  if (
    typeof safeIntent.type !== 'string' ||
    !Object.hasOwn(SCHEMAS, safeIntent.type)
  ) {
    throw new TypeError('Intent type is not allowed');
  }

  const schema = SCHEMAS[safeIntent.type];
  const allowed = new Set(['type', ...schema.required, ...schema.optional]);
  for (const key of Object.keys(safeIntent)) {
    if (!allowed.has(key)) {
      throw new TypeError(`Intent contains unknown field: ${key}`);
    }
  }
  for (const key of schema.required) {
    if (!Object.hasOwn(safeIntent, key)) {
      throw new TypeError(`Intent requires ${key}`);
    }
  }

  validateFields(safeIntent);
  validateJsonValue(safeIntent, 0);
  return safeIntent;
}

function validateFields(intent) {
  if (intent.type === 'chat.publish') {
    boundedText(intent.content, 'content', 1, 8000);
    optionalText(intent, 'target', 256);
    optionalText(intent, 'task_id', 256);
    optionalText(intent, 'in_reply_to', 256);
  } else if (intent.type === 'task.create') {
    boundedText(intent.title, 'title', 1, 512);
    boundedText(intent.owner, 'owner', 1, 128);
    boundedText(intent.priority, 'priority', 1, 32);
  } else if (intent.type === 'task.retry.request') {
    boundedText(intent.task_id, 'task_id', 1, 256);
  } else if (intent.type === 'action.preview') {
    boundedText(intent.action, 'action', 1, 128);
    if (
      Object.hasOwn(intent, 'parameters') &&
      !isPlainObject(intent.parameters)
    ) {
      throw new TypeError('parameters must be an object');
    }
  } else if (intent.type === 'host.open_vscode') {
    optionalText(intent, 'path', 1024);
  }
}

function optionalText(intent, key, maximum) {
  if (Object.hasOwn(intent, key)) boundedText(intent[key], key, 1, maximum);
}

function boundedText(value, name, minimum, maximum) {
  if (
    typeof value !== 'string' ||
    value.length < minimum ||
    value.length > maximum
  ) {
    throw new TypeError(`${name} must contain ${minimum}-${maximum} characters`);
  }
}

function serializeIntent(intent) {
  try {
    const serialized = JSON.stringify(intent);
    if (typeof serialized !== 'string') throw new TypeError('not serializable');
    return serialized;
  } catch {
    throw new TypeError('Intent must be JSON serializable');
  }
}

function validateJsonValue(value, depth) {
  if (depth > 8) throw new RangeError('Intent nesting is too deep');
  if (value === null || typeof value === 'boolean') return;
  if (typeof value === 'string') {
    if (value.length > 8192) throw new RangeError('Intent string is too large');
    return;
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) throw new TypeError('Intent number must be finite');
    return;
  }
  if (Array.isArray(value)) {
    if (value.length > 100) throw new RangeError('Intent array is too large');
    for (const item of value) validateJsonValue(item, depth + 1);
    return;
  }
  if (!isPlainObject(value)) throw new TypeError('Intent contains an invalid value');
  const entries = Object.entries(value);
  if (entries.length > 100) throw new RangeError('Intent object is too large');
  for (const [key, item] of entries) {
    if (key.length > 128 || key === '__proto__' || key === 'constructor') {
      throw new TypeError('Intent contains an invalid field name');
    }
    validateJsonValue(item, depth + 1);
  }
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

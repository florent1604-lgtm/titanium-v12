import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const html = await readFile(
  new URL('../../collab_ui/index.html', import.meta.url),
  'utf8',
);
const css = await readFile(
  new URL('../../collab_ui/styles.css', import.meta.url),
  'utf8',
);

test('keeps the permanent PAPER ONLY guard visible in the compact layout', () => {
  assert.match(
    html,
    /class="compact-guard"[^>]*aria-label="Garde permanente"[\s\S]*?PAPER ONLY[\s\S]*?RÉEL INTERDIT/,
  );
  assert.match(
    css,
    /@media \(max-width: 720px\)[\s\S]*?\.compact-guard\s*\{[^}]*display:\s*flex/,
  );
});

test('mounts the interactive shell through an ES module without stale controls', () => {
  assert.match(html, /<main class="workspace" data-command-deck-root/);
  assert.match(html, /<script type="module" src="\.\/app\.mjs"><\/script>/);
  assert.doesNotMatch(html, /data-task-1-inert/);
});

test('lets operator status labels wrap instead of truncating them', () => {
  assert.match(
    css,
    /\.agent-row small\s*\{[^}]*white-space:\s*normal[^}]*text-overflow:\s*clip/,
  );
});

test('clamps the compact conversation to the viewport and wraps journal text', () => {
  assert.match(
    css,
    /@media \(max-width: 720px\)[\s\S]*?\.conversation\s*\{[^}]*width:\s*100%[^}]*max-width:\s*100vw/,
  );
  assert.match(
    css,
    /\.message p\s*\{[^}]*overflow-wrap:\s*anywhere/,
  );
});

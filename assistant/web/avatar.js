/**
 * assistant/web/avatar.js — Renderer Three.js + @pixiv/three-vrm
 *
 * Architecture :
 *   - Charge le fichier VRM depuis /assistant/<vrm_file>
 *   - Animation idle : clignement yeux, léger mouvement tête, respiration
 *   - Lip-sync : reçoit frames via WebSocket → blend shapes en temps réel
 *   - Interpolation douce de tous les blendshapes (pas de saut brutal)
 *   - Expressions faciales : neutral, happy, thinking
 */

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { VRMLoaderPlugin, VRMUtils, VRMExpressionPresetName } from '@pixiv/three-vrm';

// ── Config ───────────────────────────────────────────────────────────────────

const VRM_FILE      = window.TITAN_VRM_FILE || 'VRoid_V110_Male_v1.1.3.vrm';
const WS_URL        = `ws://${location.host}/titan/ws`;
const LERP_SPEED    = 0.25;   // vitesse d'interpolation blendshapes (0-1)
const BLINK_MIN_MS  = 2000;
const BLINK_MAX_MS  = 6000;

// ── État global ──────────────────────────────────────────────────────────────

let vrm       = null;
let mixer     = null;
let isSpeaking = false;

// Cibles de blendshape (interpolées chaque frame)
const shapeTargets  = {};
const shapeCurrent  = {};

// Noms de mappage entre notre protocole et VRM Expression Manager
// VRM0 : a, i, u, e, o | VRM1 : aa, ih, ou, ee, oh
const VISEME_MAP = {
  aa:       [VRMExpressionPresetName.Aa,  'aa', 'A'],
  ih:       [VRMExpressionPresetName.Ih,  'ih', 'I'],
  ou:       [VRMExpressionPresetName.Ou,  'ou', 'U'],
  ee:       [VRMExpressionPresetName.Ee,  'ee', 'E'],
  oh:       [VRMExpressionPresetName.Oh,  'oh', 'O'],
  blink:    [VRMExpressionPresetName.Blink, 'blink'],
  blinkLeft:  [VRMExpressionPresetName.BlinkLeft,  'blinkLeft'],
  blinkRight: [VRMExpressionPresetName.BlinkRight, 'blinkRight'],
  happy:    [VRMExpressionPresetName.Happy, 'joy'],
  angry:    [VRMExpressionPresetName.Angry, 'angry'],
  sad:      [VRMExpressionPresetName.Sad,   'sorrow'],
  surprised:[VRMExpressionPresetName.Surprised, 'surprised'],
  neutral:  [VRMExpressionPresetName.Neutral, 'neutral'],
};

// ARKit (perfect sync 52 blendshapes) — noms alternatifs
const ARKIT_ALIASES = {
  jawOpen:        'jawOpen',
  mouthFunnel:    'mouthFunnel',
  mouthPucker:    'mouthPucker',
  mouthSmileLeft: 'mouthSmileLeft',
  mouthSmileRight:'mouthSmileRight',
};

// ── Scene setup ───────────────────────────────────────────────────────────────

const container = document.getElementById('canvas-container');
const renderer  = new THREE.WebGLRenderer({
  antialias: true,
  alpha: true,
  powerPreference: 'low-power',
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(container.clientWidth, container.clientHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.shadowMap.enabled = false;   // économie CPU
container.appendChild(renderer.domElement);

const scene  = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(
  30,
  container.clientWidth / container.clientHeight,
  0.1,
  20,
);
// Cadrage buste
camera.position.set(0, 1.35, 2.2);
camera.lookAt(0, 1.35, 0);

// Éclairage doux
const ambientLight = new THREE.AmbientLight(0xffffff, 0.7);
scene.add(ambientLight);

const dirLight = new THREE.DirectionalLight(0x4fc3f7, 1.2);
dirLight.position.set(1, 2, 1.5);
scene.add(dirLight);

const rimLight = new THREE.DirectionalLight(0x7986cb, 0.4);
rimLight.position.set(-2, 1, -1);
scene.add(rimLight);

// ── Chargement VRM ────────────────────────────────────────────────────────────

async function loadVRM(url) {
  const loadingOverlay = document.getElementById('loading-overlay');
  const loadingText    = document.getElementById('loading-text');

  const loader = new GLTFLoader();
  loader.register(parser => new VRMLoaderPlugin(parser));

  return new Promise((resolve, reject) => {
    loader.load(
      url,
      gltf => {
        const model = gltf.userData.vrm;
        if (!model) {
          reject(new Error('Pas de VRM dans ce fichier GLTF'));
          return;
        }

        // Optimiser le rendu (removeUnnecessaryVertices existe en v2+, combineSkeletons supprimé)
        try { VRMUtils.removeUnnecessaryVertices(gltf.scene); } catch (_) {}

        // Rotation pour Three.js (VRM0 vs VRM1)
        if (model.meta?.metaVersion === '0') {
          model.scene.rotation.y = Math.PI;
        }

        scene.add(model.scene);

        if (loadingOverlay) {
          loadingOverlay.classList.add('hidden');
        }

        console.log('[Avatar] VRM chargé:', model.meta?.name || url);
        resolve(model);
      },
      xhr => {
        const pct = Math.round(xhr.loaded / xhr.total * 100);
        if (loadingText) loadingText.textContent = `CHARGEMENT ${pct}%`;
      },
      err => {
        console.error('[Avatar] Erreur chargement VRM:', err);
        if (loadingText) loadingText.textContent = 'ERREUR CHARGEMENT';
        reject(err);
      }
    );
  });
}

// ── Helpers blendshapes ───────────────────────────────────────────────────────

/**
 * Résout le nom d'une expression dans le VRM (tente plusieurs alias).
 * Retourne le nom utilisable ou null.
 */
function resolveExpressionName(key) {
  if (!vrm?.expressionManager) return null;

  const em = vrm.expressionManager;

  // Tableau d'alias VRM prédéfinis
  const aliases = VISEME_MAP[key];
  if (aliases) {
    for (const alias of aliases) {
      try {
        if (em.getExpression(alias) !== undefined) return alias;
      } catch {}
    }
  }

  // Essai direct (custom expression ARKit)
  try {
    if (em.getExpression(key) !== undefined) return key;
  } catch {}

  // Accès direct au morphTarget via la scène
  return null;
}

/**
 * Applique une valeur à un blendshape (gère VRM + ARKit custom).
 */
function applyShape(key, value) {
  if (!vrm) return;

  const name = resolveExpressionName(key);
  if (name && vrm.expressionManager) {
    try {
      vrm.expressionManager.setValue(name, Math.max(0, Math.min(1, value)));
      return;
    } catch {}
  }

  // Fallback : chercher dans les morphTargets de la scène
  setMorphTarget(key, value);
}

function setMorphTarget(key, value) {
  vrm?.scene.traverse(obj => {
    if (obj.isMesh && obj.morphTargetDictionary) {
      const idx = obj.morphTargetDictionary[key];
      if (idx !== undefined) {
        obj.morphTargetInfluences[idx] = Math.max(0, Math.min(1, value));
      }
    }
  });
}

// ── Interpolation des blendshapes ─────────────────────────────────────────────

function setShapeTarget(key, value) {
  shapeTargets[key] = Math.max(0, Math.min(1, value));
}

function lerpAllShapes(delta) {
  const k = 1 - Math.exp(-LERP_SPEED * delta * 60);
  const allKeys = new Set([...Object.keys(shapeTargets), ...Object.keys(shapeCurrent)]);
  for (const key of allKeys) {
    const target  = shapeTargets[key]  ?? 0;
    const current = shapeCurrent[key]  ?? 0;
    const next    = current + (target - current) * k;
    shapeCurrent[key] = next;
    applyShape(key, next);
  }
}

function resetAllTargets() {
  for (const key of Object.keys(shapeTargets)) {
    shapeTargets[key] = 0;
  }
  // Forcer fermeture bouche
  ['aa','ih','ou','ee','oh','jawOpen','mouthFunnel','mouthPucker'].forEach(k => {
    shapeTargets[k] = 0;
  });
}

// ── Animation idle ────────────────────────────────────────────────────────────

let blinkTimeout = null;

function scheduleNextBlink() {
  const delay = BLINK_MIN_MS + Math.random() * (BLINK_MAX_MS - BLINK_MIN_MS);
  blinkTimeout = setTimeout(performBlink, delay);
}

async function performBlink() {
  setShapeTarget('blink', 1.0);
  setShapeTarget('blinkLeft', 1.0);
  setShapeTarget('blinkRight', 1.0);
  await sleep(90);
  setShapeTarget('blink', 0.0);
  setShapeTarget('blinkLeft', 0.0);
  setShapeTarget('blinkRight', 0.0);
  scheduleNextBlink();
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// Mouvements de tête idle (sinusoïdaux très subtils)
const headMotion = {
  time: 0,
  update(dt) {
    if (!vrm?.humanoid) return;
    this.time += dt;
    const t = this.time;

    // Oscillation douce
    const nodX = Math.sin(t * 0.4) * 0.015;
    const nodY = Math.sin(t * 0.3) * 0.012;
    const nodZ = Math.sin(t * 0.25) * 0.008;

    vrm.humanoid.getNormalizedBoneNode('head')?.rotation.set(nodX, nodY, nodZ);

    // Respiration (léger mouvement de la poitrine)
    const breathe = Math.sin(t * 0.7) * 0.003;
    vrm.humanoid.getNormalizedBoneNode('spine')?.rotation.set(breathe, 0, 0);
  }
};

// État "thinking" — tête légèrement inclinée, regard en bas à gauche
let _isThinking = false;
const thinkMotion = {
  time: 0,
  update(dt) {
    if (!vrm?.humanoid || !_isThinking) return;
    this.time += dt;
    const t = this.time;
    // Inclinaison douce de la tête comme si on réfléchit
    const tiltX =  0.06 + Math.sin(t * 0.8) * 0.01;
    const tiltZ = -0.05 + Math.sin(t * 0.5) * 0.008;
    vrm.humanoid.getNormalizedBoneNode('head')?.rotation.set(tiltX, -0.04, tiltZ);
  },
};

// Regard naturel (yeux bougent légèrement)
const eyeMotion = {
  time: 0,
  update(dt) {
    if (!vrm?.humanoid) return;
    this.time += dt * 0.5;
    const t    = this.time;
    const lx   = Math.sin(t * 0.7) * 0.08;
    const ly   = Math.sin(t * 0.5) * 0.05;
    vrm.humanoid.getNormalizedBoneNode('leftEye')?.rotation.set(ly, lx, 0);
    vrm.humanoid.getNormalizedBoneNode('rightEye')?.rotation.set(ly, lx, 0);
  }
};

// ── WebSocket ─────────────────────────────────────────────────────────────────

let ws = null;
let wsReconnectTimer = null;

function connectWS() {
  if (ws?.readyState === WebSocket.OPEN) return;

  try {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log('[Avatar] WS connecté');
      clearTimeout(wsReconnectTimer);
    };

    ws.onmessage = evt => {
      try {
        const msg = JSON.parse(evt.data);
        handleWsMessage(msg);
      } catch (e) {
        console.warn('[Avatar] WS message invalide:', e);
      }
    };

    ws.onclose = () => {
      console.log('[Avatar] WS fermé — reconnexion dans 3s');
      wsReconnectTimer = setTimeout(connectWS, 3000);
    };

    ws.onerror = err => {
      console.warn('[Avatar] WS erreur:', err);
    };
  } catch (e) {
    console.warn('[Avatar] WS connexion échouée:', e);
    wsReconnectTimer = setTimeout(connectWS, 5000);
  }
}

// ── Gestion de l'overlay d'état ──────────────────────────────────────────────

const STATE_CONFIG = {
  listening: { icon: '🎙️', label: 'Écoute en cours...', cls: 'state-listening' },
  thinking:  { icon: '⏳', label: 'Titan réfléchit...', cls: 'state-thinking'  },
  speaking:  { icon: '💬', label: 'Titan répond',       cls: 'state-speaking'  },
  idle:      { icon: '🎙️', label: 'Ctrl+Alt pour parler', cls: 'state-hint'   },
};

let _hideOverlayTimer = null;

function setUiState(state, customMessage = '') {
  const overlay   = document.getElementById('state-overlay');
  const iconEl    = document.getElementById('state-icon');
  const labelEl   = document.getElementById('state-label');
  const statusDot = document.getElementById('status-dot');

  if (!overlay) return;

  // Effacer les classes d'état précédentes
  overlay.classList.remove('state-listening', 'state-thinking', 'state-speaking', 'state-hint');
  clearTimeout(_hideOverlayTimer);

  const cfg = STATE_CONFIG[state] || STATE_CONFIG.idle;
  if (iconEl)  iconEl.textContent  = cfg.icon;
  if (labelEl) labelEl.textContent = customMessage || cfg.label;
  overlay.classList.add(cfg.cls);

  if (state === 'idle') {
    // Afficher brièvement "Ctrl+Alt pour parler" puis masquer
    overlay.classList.add('visible');
    _hideOverlayTimer = setTimeout(() => overlay.classList.remove('visible'), 3000);
  } else {
    overlay.classList.add('visible');
  }

  // Status dot
  if (statusDot) {
    statusDot.classList.toggle('speaking', state === 'speaking');
    statusDot.classList.toggle('loading',  state === 'thinking' || state === 'listening');
  }
}

function handleWsMessage(msg) {
  const voiceIndicator = document.getElementById('voice-indicator');
  const statusDot      = document.getElementById('status-dot');

  switch (msg.type) {

    case 'state':
      // Etat Ctrl+Alt : listening / thinking / speaking / idle
      setUiState(msg.state, msg.message || '');
      _isThinking = (msg.state === 'thinking');
      if (msg.state !== 'thinking') thinkMotion.time = 0;
      break;

    case 'blend':
      if (msg.shapes) {
        _lastWsFrameTime = Date.now();   // marquer la réception d'un frame WS
        for (const [key, val] of Object.entries(msg.shapes)) {
          setShapeTarget(key, val);
        }
      }
      break;

    case 'expression':
      if (msg.name) {
        setShapeTarget(msg.name, msg.weight ?? 1.0);
        if (msg.duration > 0) {
          setTimeout(() => setShapeTarget(msg.name, 0), msg.duration);
        }
      }
      break;

    case 'speaking':
      isSpeaking = !!msg.value;
      if (voiceIndicator) voiceIndicator.classList.toggle('active', isSpeaking);
      if (isSpeaking) {
        setUiState('speaking');
      } else {
        setUiState('idle');
        resetAllTargets();
      }
      break;

    case 'reset':
      resetAllTargets();
      isSpeaking = false;
      if (voiceIndicator) voiceIndicator.classList.remove('active');
      setUiState('idle');
      break;
  }
}

// ── Animation procédurale pendant la parole ───────────────────────────────────

// Timestamp du dernier frame lip-sync reçu via WS
let _lastWsFrameTime = 0;

// Animation de mâchoire générée localement quand aucun frame WS n'arrive
// (WebSocket lent, pas de client connecté, etc.)
const speechMotion = {
  time: 0,

  update(dt) {
    if (!vrm || !isSpeaking) return;

    const msSinceFrame = Date.now() - _lastWsFrameTime;

    // Si un frame WS est arrivé récemment (<= 150ms), laisser le WS contrôler
    if (msSinceFrame <= 150) return;

    // Fallback procédural : oscillation sinusoïdale naturelle de la bouche
    this.time += dt;
    const t = this.time;

    // Deux fréquences combinées → mouvement plus naturel
    const jaw = Math.max(0,
      Math.sin(t * 9.5) * 0.3 +
      Math.sin(t * 6.1) * 0.15
    );

    setShapeTarget('aa',      Math.max(0, jaw));
    setShapeTarget('oh',      Math.max(0, jaw * 0.4));
    setShapeTarget('jawOpen', Math.max(0, jaw * 0.6));
  },
};

// ── Boucle de rendu ───────────────────────────────────────────────────────────

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const delta = clock.getDelta();

  if (vrm) {
    if (_isThinking) {
      thinkMotion.update(delta);
    } else {
      headMotion.update(delta);
    }
    eyeMotion.update(delta);
    speechMotion.update(delta);   // ← fallback procédural
    lerpAllShapes(delta);
    vrm.update(delta);
  }

  renderer.render(scene, camera);
}

// ── Resize ────────────────────────────────────────────────────────────────────

window.addEventListener('resize', () => {
  const w = container.clientWidth;
  const h = container.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
});

// ── Init ──────────────────────────────────────────────────────────────────────

(async () => {
  const statusDot = document.getElementById('status-dot');
  if (statusDot) statusDot.classList.add('loading');

  try {
    vrm = await loadVRM(`/assistant/${VRM_FILE}`);
    scheduleNextBlink();
    connectWS();
    if (statusDot) statusDot.classList.remove('loading');
    console.log('[Avatar] Initialisé avec succès');
  } catch (err) {
    console.error('[Avatar] Échec d\'initialisation:', err);
    const loadingText = document.getElementById('loading-text');
    if (loadingText) loadingText.textContent = 'ERREUR: ' + err.message;
    if (statusDot) statusDot.style.background = '#ef5350';
  }

  animate();
})();

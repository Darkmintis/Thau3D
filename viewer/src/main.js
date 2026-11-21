import './style.css';
import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

// ---------------------------------------------------------------- constants
const EYE = 1.62;
const BODY = 1.74;
const RADIUS = 0.2;
const STEP_UP = 0.26;
const STEP_DOWN = 0.36;
const GRAVITY = 18.0;
const WALK_SPEED = 2.65;
const RUN_SPEED = 4.5;

const params = new URLSearchParams(location.search);
const MODEL_URL = params.get('model') || 'models/house.glb';
const MANIFEST_URL = MODEL_URL.replace(/\.glb$/i, '.manifest.json');
const isTouch = window.matchMedia('(pointer: coarse)').matches || navigator.maxTouchPoints > 0;

const $ = (selector) => document.querySelector(selector);
const els = {
  viewport: $('#viewport'),
  name: $('#building-name'),
  stat: $('#building-stat'),
  spaceList: $('#space-list'),
  spaceTotal: $('#space-total'),
  status: $('#status-label'),
  walkButton: $('#walk-button'),
  lightsButton: $('#lights-button'),
  lightsLabel: $('#lights-label'),
  resume: $('#resume-card'),
  loading: $('#loading'),
  progressBar: $('#progress-bar'),
  progressCaption: $('#progress-caption'),
  loadingTitle: $('#loading-title'),
  loadingMessage: $('#loading-message'),
  errorActions: $('#error-actions'),
  touchControls: $('#touch-controls'),
};

const state = {
  mode: 'orbit',
  night: false,
  nightBlend: 0,
  nightTarget: 0,
  lightsOn: false,
  lightBlend: 0,
  lightTarget: 0,
  isolatedStorey: null,
  manifest: null,
  footY: 0,
  velocityY: 0,
  grounded: false,
  bobClock: 0,
  focusTween: null,
};

if (isTouch) document.body.classList.add('touch');

// ------------------------------------------------------------------ renderer
const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
renderer.domElement.setAttribute('aria-label', 'Interactive building model');
els.viewport.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color('#b9cdd8');
scene.fog = new THREE.Fog('#b9cdd8', 55, 190);

const camera = new THREE.PerspectiveCamera(58, 1, 0.06, 400);
camera.position.set(9, 8, 16);

// ---------------------------------------------------------------- sky dome
const skyMaterial = new THREE.ShaderMaterial({
  uniforms: { uNight: { value: 0 } },
  vertexShader: `
    varying vec3 vDir;
    void main() {
      vDir = normalize(position);
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: `
    uniform float uNight;
    varying vec3 vDir;
    float hash(vec2 p) {
      p = fract(p * vec2(123.34, 456.21));
      p += dot(p, p + 45.32);
      return fract(p.x * p.y);
    }
    void main() {
      float up = clamp(vDir.y * 0.5 + 0.5, 0.0, 1.0);
      float grad = smoothstep(0.0, 1.0, up);
      vec3 dayLow = vec3(0.72, 0.79, 0.84);
      vec3 dayHigh = vec3(0.28, 0.47, 0.65);
      vec3 nightLow = vec3(0.09, 0.11, 0.14);
      vec3 nightHigh = vec3(0.02, 0.03, 0.07);
      vec3 dayColor = mix(dayLow, dayHigh, grad);
      vec3 nightColor = mix(nightLow, nightHigh, grad);
      vec2 grid = vec2(atan(vDir.z, vDir.x) * 380.0, asin(vDir.y) * 300.0);
      vec2 cell = floor(grid);
      float star = (1.0 - smoothstep(0.01, 0.05, length(fract(grid) - 0.5)))
                 * step(0.9985, hash(cell)) * smoothstep(0.02, 0.30, vDir.y);
      nightColor += vec3(star * 0.5);
      gl_FragColor = vec4(mix(dayColor, nightColor, uNight), 1.0);
    }
  `,
  side: THREE.BackSide,
  depthWrite: false,
  depthTest: false,
  toneMapped: false,
});
const sky = new THREE.Mesh(new THREE.SphereGeometry(180, 32, 20), skyMaterial);
sky.frustumCulled = false;
sky.renderOrder = -1000;
scene.add(sky);

// ------------------------------------------------------------------- lights
const hemi = new THREE.HemisphereLight(0xdcecf7, 0x6d675e, 0.85);
scene.add(hemi);

const ambient = new THREE.AmbientLight(0xffe8d2, 0.28);
scene.add(ambient);

const sun = new THREE.DirectionalLight(0xffe7c8, 2.6);
sun.position.set(-12, 20, 14);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.12;
sun.shadow.camera.near = 1;
sun.shadow.camera.far = 90;
scene.add(sun);
scene.add(sun.target);

const fill = new THREE.DirectionalLight(0xbcd3e6, 0.5);
fill.position.set(14, 9, -12);
scene.add(fill);

// Image based lighting: a neutral studio, so PBR materials read properly
const pmrem = new THREE.PMREMGenerator(renderer);
scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.5;

// ------------------------------------------------------------------- camera
const orbit = new OrbitControls(camera, renderer.domElement);
orbit.enableDamping = true;
orbit.dampingFactor = 0.07;
orbit.maxPolarAngle = Math.PI * 0.495;
orbit.minDistance = 2.5;
orbit.maxDistance = 70;
orbit.screenSpacePanning = false;

// camera look is handled in the input section below

// -------------------------------------------------------------------- input
// We drive the camera ourselves rather than using PointerLockControls: the
// browser's raw movement deltas are smoothed into a target yaw/pitch and then
// damped every frame, which is what stops the view snapping when the pointer
// re-locks or a device reports a spike.
const LOOK_SENSITIVITY = 0.0022;
const MAX_DELTA = 90;
const look = { locked: false, yaw: 0, pitch: 0, targetYaw: 0, targetPitch: 0, dragging: false, fresh: false, x: 0, y: 0 };

const keys = new Set();
const touchMove = new Set();
let jumpRequested = false;

function clamp(value, limit) {
  return Math.max(-limit, Math.min(limit, value));
}

function applyLookDelta(dx, dy) {
  look.targetYaw -= clamp(dx, MAX_DELTA) * LOOK_SENSITIVITY;
  look.targetPitch = THREE.MathUtils.clamp(
    look.targetPitch - clamp(dy, MAX_DELTA) * LOOK_SENSITIVITY * 0.85,
    -1.2,
    1.2,
  );
}

function requestLock() {
  if (isTouch || state.mode !== 'walk') return;
  const element = renderer.domElement;
  if (!element.requestPointerLock) return;
  try {
    const pending = element.requestPointerLock({ unadjustedMovement: true });
    if (pending && typeof pending.catch === 'function') {
      pending.catch(() => element.requestPointerLock());
    }
  } catch (error) {
    element.requestPointerLock();
  }
}

document.addEventListener('pointerlockchange', () => {
  look.locked = document.pointerLockElement === renderer.domElement;
  if (look.locked) {
    look.fresh = true;
    els.resume.hidden = true;
    els.status.textContent = `${storeyLabelAt(camera.position.y)} · walking`;
    return;
  }
  if (state.mode !== 'walk' || isTouch) return;
  els.resume.hidden = false;
  els.status.textContent = 'Paused · click resume to continue';
});

document.addEventListener('mousemove', (event) => {
  if (!look.locked || state.mode !== 'walk') return;
  // The first event after a lock can carry a jump from wherever the cursor sat.
  if (look.fresh) {
    look.fresh = false;
    return;
  }
  applyLookDelta(event.movementX || 0, event.movementY || 0);
});

window.addEventListener('keydown', (event) => {
  if (state.mode !== 'walk') return;
  if (['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight'].includes(event.code)) {
    keys.add(event.code);
    event.preventDefault();
  }
  if (event.code === 'Space') {
    jumpRequested = true;
    event.preventDefault();
  }
  if (event.code === 'Escape' && !isTouch) exitWalk();
});
window.addEventListener('keyup', (event) => keys.delete(event.code));
window.addEventListener('blur', () => {
  keys.clear();
  touchMove.clear();
});

renderer.domElement.addEventListener('pointerdown', (event) => {
  if (state.mode !== 'walk' || event.pointerType === 'mouse') return;
  look.dragging = true;
  look.fresh = true;
  look.x = event.clientX;
  look.y = event.clientY;
  renderer.domElement.setPointerCapture?.(event.pointerId);
});
renderer.domElement.addEventListener('pointermove', (event) => {
  if (!look.dragging || state.mode !== 'walk') return;
  const dx = event.clientX - look.x;
  const dy = event.clientY - look.y;
  look.x = event.clientX;
  look.y = event.clientY;
  if (look.fresh) {
    look.fresh = false;
    return;
  }
  applyLookDelta(dx, dy);
});
const endLook = () => {
  look.dragging = false;
};
renderer.domElement.addEventListener('pointerup', endLook);
renderer.domElement.addEventListener('pointercancel', endLook);

for (const button of document.querySelectorAll('[data-move]')) {
  const action = button.dataset.move;
  const press = (event) => {
    event.preventDefault();
    touchMove.add(action);
    if (action === 'run') button.classList.add('active');
  };
  const release = (event) => {
    event.preventDefault();
    touchMove.delete(action);
    button.classList.remove('active');
  };
  button.addEventListener('pointerdown', press);
  button.addEventListener('pointerup', release);
  button.addEventListener('pointercancel', release);
  button.addEventListener('pointerleave', release);
  button.addEventListener('contextmenu', (event) => event.preventDefault());
}
$('#jump-button').addEventListener('click', (event) => {
  event.preventDefault();
  jumpRequested = true;
});

// ---------------------------------------------------------------------- load
let model = null;
const glassyMaterials = [];

async function loadModel() {
  const loader = new GLTFLoader();
  try {
    els.progressCaption.textContent = 'Loading geometry';
    const gltf = await loader.loadAsync(MODEL_URL, (event) => {
      if (!event.total) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      els.progressBar.style.width = `${percent}%`;
      els.progressCaption.textContent = `Loading geometry · ${percent}%`;
    });
    els.progressCaption.textContent = 'Reading manifest';
    const manifest = await fetch(MANIFEST_URL).then((response) => {
      if (!response.ok) throw new Error(`manifest ${response.status}`);
      return response.json();
    });

    state.manifest = manifest;
    model = gltf.scene;
    model.traverse((object) => {
      if (!object.isMesh) return;
      const material = object.material;
      if (material) {
        if (material.transparent) {
          material.depthWrite = false;
          material.envMapIntensity = 0.12;
          glassyMaterials.push(material);
        } else {
          material.envMapIntensity = 0.85;
        }
        material.needsUpdate = true;
      }
      // the site only receives: letting it cast makes its own top face self-shadow
      object.castShadow = !material?.transparent && Boolean(object.userData.storey);
      object.receiveShadow = true;
    });
    scene.add(model);

    collectDoors(model);
    buildLights(manifest.luminaires || []);
    addHorizon(manifest);
    frameBuilding(manifest);
    buildPanel(manifest);
    applyStoreyFilter(null);
    els.progressBar.style.width = '100%';
    els.progressCaption.textContent = 'Ready';
    els.loading.classList.add('loaded');
    els.walkButton.disabled = false;
    els.status.textContent = 'Exterior overview';
    els.name.textContent = manifest.name || 'Untitled building';
    const total = (manifest.spaces || []).reduce((sum, space) => sum + space.area, 0);
    els.stat.textContent = `${manifest.storeys.length} storeys · ${manifest.spaces.length} spaces · ${total.toFixed(1)} m²`;
    els.spaceTotal.textContent = `${total.toFixed(0)} m²`;
  } catch (error) {
    console.error('Thau3D viewer failed to load', error);
    els.loadingTitle.textContent = 'The model could not be opened.';
    els.loadingMessage.textContent = String(error?.message || error);
    els.progressCaption.textContent = 'Load failed';
    els.errorActions.hidden = false;
  }
}

$('#retry-button').addEventListener('click', () => location.reload());

// ------------------------------------------------------------------- lights
// ------------------------------------------------------------------- doors
const doors = [];

function collectDoors(root) {
  root.traverse((object) => {
    const data = object.userData;
    if (!data || !data.door) return;
    doors.push({ object, closed: Number(data.closed) || 0, open: Number(data.open) || 0 });
  });
}

function updateDoors(delta) {
  if (!doors.length) return;
  const walking = state.mode === 'walk';
  for (const door of doors) {
    const dx = camera.position.x - door.object.position.x;
    const dz = camera.position.z - door.object.position.z;
    const near = walking && dx * dx + dz * dz < 6.25;
    const target = near ? door.open : door.closed;
    door.object.rotation.y = THREE.MathUtils.damp(door.object.rotation.y, target, 7, delta);
  }
}

let luminaires = [];

function buildLights(entries) {
  luminaires = entries.map((entry) => {
    const light = new THREE.PointLight(0xffd3a0, 0, entry.distance || 6, 2);
    light.position.set(entry.position[0], entry.position[1], entry.position[2]);
    light.userData.full = entry.intensity || 2;
    scene.add(light);
    return light;
  });
}

// ------------------------------------------------------------- horizon ground
let horizon = null;

function addHorizon(manifest) {
  const site = manifest.site || {};
  const groundY = Array.isArray(site.max) ? site.max[1] : 0;
  const material = new THREE.MeshStandardMaterial({
    color: new THREE.Color(site.surface || '#7d735f'),
    roughness: 1,
    metalness: 0,
    dithering: true,
  });
  horizon = new THREE.Mesh(new THREE.CircleGeometry(340, 72), material);
  horizon.rotation.x = -Math.PI / 2;
  horizon.position.y = groundY - 0.03;
  horizon.receiveShadow = true;
  scene.add(horizon);
}

// ------------------------------------------------------------------ framing
function frameBuilding(manifest) {
  const storeys = manifest.storeys || [];
  const top = storeys.length ? storeys[storeys.length - 1].top : 8;
  const bounds = manifest.bounds || { min: [0, 0, -10], max: [10, top, 0] };
  const centre = new THREE.Vector3(
    (bounds.min[0] + bounds.max[0]) / 2,
    (bounds.min[1] + bounds.max[1]) / 2,
    (bounds.min[2] + bounds.max[2]) / 2,
  );
  const size = new THREE.Vector3(
    bounds.max[0] - bounds.min[0],
    bounds.max[1] - bounds.min[1],
    bounds.max[2] - bounds.min[2],
  );

  const distance = Math.max(size.y * 1.9, Math.max(size.x, size.z) * 1.75, 12);
  orbit.target.copy(centre);
  camera.position.set(centre.x - distance * 0.52, centre.y + distance * 0.42, centre.z + distance);
  camera.lookAt(centre);
  orbit.update();

  sun.target.position.copy(centre);
  sun.position.set(centre.x - size.x * 2.2, top + size.y * 2.4, centre.z + size.z * 2.2);
  const extent = Math.max(size.x, size.y, size.z) * 1.6;
  sun.shadow.camera.left = -extent;
  sun.shadow.camera.right = extent;
  sun.shadow.camera.top = extent;
  sun.shadow.camera.bottom = -extent;
  sun.shadow.camera.updateProjectionMatrix();

  scene.fog.near = Math.max(24, distance * 1.2);
  scene.fog.far = distance * 7.5;
}

// ------------------------------------------------------------------- panel
function buildPanel(manifest) {
  els.spaceList.innerHTML = '';
  for (const storey of manifest.storeys) {
    const row = document.createElement('div');
    row.className = 'storey-row';

    const title = document.createElement('button');
    title.type = 'button';
    title.className = 'storey-title';
    title.dataset.storey = storey.id;
    title.innerHTML = `<span>${storey.id.toUpperCase()}</span><span>${storey.area_net.toFixed(1)} m²</span>`;
    title.addEventListener('click', () => {
      const next = state.isolatedStorey === storey.id ? null : storey.id;
      setStorey(next);
    });
    row.appendChild(title);

    for (const space of manifest.spaces.filter((item) => item.storey === storey.id)) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'space-button';
      button.dataset.space = space.id;
      button.innerHTML = `<span>${space.name}</span><small>${space.area.toFixed(1)} m²</small>`;
      button.addEventListener('click', () => focusSpace(space));
      row.appendChild(button);
    }
    els.spaceList.appendChild(row);
  }
}

function setStorey(storeyId) {
  state.isolatedStorey = storeyId;
  applyStoreyFilter(storeyId);
  for (const button of document.querySelectorAll('.storey-title')) {
    button.classList.toggle('active', button.dataset.storey === storeyId);
  }
  if (!storeyId) {
    els.status.textContent = 'Exterior overview';
    return;
  }
  const storey = state.manifest.storeys.find((item) => item.id === storeyId);
  els.status.textContent = `${titleCase(storeyId)} isolated`;
  if (storey) {
    const bounds = state.manifest.bounds;
    const centre = new THREE.Vector3((bounds.min[0] + bounds.max[0]) / 2, storey.base + 0.6, (bounds.min[2] + bounds.max[2]) / 2);
    const size = Math.max(bounds.max[0] - bounds.min[0], bounds.max[2] - bounds.min[2]);
    orbit.target.copy(centre);
    tweenCamera(new THREE.Vector3(centre.x + size * 0.2, storey.base + size * 0.95, centre.z + size * 0.95), centre);
  }
}

function applyStoreyFilter(storeyId) {
  if (!model) return;
  model.traverse((object) => {
    if (!object.isMesh) return;
    const id = object.userData.storey || '';
    object.visible = !storeyId || id === '' || id === storeyId;
  });
}

function focusSpace(space) {
  if (!space) return;
  if (state.mode === 'walk') exitWalk();
  const storey = state.manifest.storeys.find((item) => item.id === space.storey);
  if (state.isolatedStorey !== storey?.id) setStorey(space.storey);
  const [x0, y0, x1, y1] = space.rect;
  const width = x1 - x0;
  const depth = y1 - y0;
  const centre = new THREE.Vector3((x0 + x1) / 2, (storey?.base || 0) + 0.9, -(y0 + y1) / 2);
  const reach = Math.max(width, depth, 2.4);
  tweenCamera(new THREE.Vector3(centre.x + reach * 0.55, centre.y + reach * 1.15, centre.z + reach * 0.95), centre);
  for (const button of document.querySelectorAll('.space-button')) {
    button.classList.toggle('active', button.dataset.space === space.id);
  }
  els.status.textContent = `${space.name} · ${space.area.toFixed(1)} m²`;
}

function tweenCamera(position, target) {
  state.focusTween = {
    from: camera.position.clone(),
    fromTarget: orbit.target.clone(),
    to: position.clone(),
    toTarget: target.clone(),
    start: performance.now(),
    duration: 620,
  };
}

// --------------------------------------------------------------------- walk
function storeyForHeight(y) {
  const storeys = state.manifest?.storeys || [];
  for (const storey of storeys) {
    if (y >= storey.base - 0.4 && y < storey.top + 0.9) return storey;
  }
  return storeys[storeys.length - 1] || null;
}

function storeyLabelAt(y) {
  const storey = storeyForHeight(y);
  if (!storey) return 'Ground';
  const index = state.manifest.storeys.indexOf(storey);
  if (index === state.manifest.storeys.length - 1 && y > storey.top + 0.2) return 'Roof';
  return titleCase(storey.id);
}

function titleCase(value) {
  return String(value).replace(/[-_]/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function enterWalk() {
  if (!model || !state.manifest) return;
  state.mode = 'walk';
  document.body.classList.add('walking');
  setStorey(null);
  if (!state.lightsOn) setLights(true);
  orbit.enabled = false;
  const spawn = state.manifest.spawn;
  camera.position.set(spawn.position[0], spawn.position[1], spawn.position[2]);
  camera.rotation.set(0, spawn.yaw || 0, 0, 'YXZ');
  look.yaw = look.targetYaw = spawn.yaw || 0;
  look.pitch = look.targetPitch = 0;
  state.footY = spawn.position[1] - EYE;
  state.velocityY = 0;
  state.grounded = true;
  keys.clear();
  touchMove.clear();
  els.walkButton.querySelector('span').textContent = 'Exit walk';
  els.status.textContent = `${storeyLabelAt(camera.position.y)} · walking`;
  requestLock();
}

function exitWalk() {
  state.mode = 'orbit';
  document.body.classList.remove('walking');
  els.resume.hidden = true;
  look.dragging = false;
  if (document.pointerLockElement) document.exitPointerLock();
  orbit.enabled = true;
  els.walkButton.querySelector('span').textContent = 'Walk inside';
  frameBuilding(state.manifest);
  els.status.textContent = 'Exterior overview';
}

function respawn() {
  const spawn = state.manifest.spawn;
  camera.position.set(spawn.position[0], spawn.position[1], spawn.position[2]);
  camera.rotation.set(0, spawn.yaw || 0, 0, 'YXZ');
  look.yaw = look.targetYaw = spawn.yaw || 0;
  look.pitch = look.targetPitch = 0;
  state.footY = spawn.position[1] - EYE;
  state.velocityY = 0;
  state.grounded = true;
}

// ------------------------------------------------------------- walk physics
function collidesAt(x, z, footY) {
  const bodyMin = footY + 0.1;
  const bodyMax = footY + BODY;
  for (const box of state.manifest.colliders) {
    if (box.max[1] <= bodyMin || box.min[1] >= bodyMax) continue;
    if (x + RADIUS > box.min[0] && x - RADIUS < box.max[0] && z + RADIUS > box.min[2] && z - RADIUS < box.max[2]) {
      return true;
    }
  }
  return false;
}

function supportAt(x, z, maxY) {
  const margin = RADIUS + 0.02;
  let best = null;
  for (const box of state.manifest.supports) {
    if (box.max[1] > maxY + 0.02) continue;
    if (x < box.min[0] - margin || x > box.max[0] + margin) continue;
    if (z < box.min[2] - margin || z > box.max[2] + margin) continue;
    if (!best || box.max[1] > best.max[1]) best = box;
  }
  return best;
}

function tryMove(dx, dz) {
  const foot = state.footY;
  const targetX = camera.position.x + dx;
  const targetZ = camera.position.z + dz;

  const attempt = (x, z) => {
    const support = supportAt(x, z, foot + STEP_UP);
    const rise = support ? support.max[1] - foot : -Infinity;
    const canStep = support && rise <= STEP_UP && rise >= -STEP_DOWN;
    const nextFoot = canStep ? support.max[1] : foot;
    if (collidesAt(x, z, nextFoot)) return false;
    camera.position.x = x;
    camera.position.z = z;
    if (canStep) {
      state.footY = nextFoot;
      state.velocityY = 0;
      state.grounded = true;
    }
    return true;
  };

  if (!attempt(targetX, targetZ)) {
    if (!attempt(targetX, camera.position.z)) attempt(camera.position.x, targetZ);
  }
}

function updateLook(delta) {
  look.yaw = THREE.MathUtils.damp(look.yaw, look.targetYaw, 16, delta);
  look.pitch = THREE.MathUtils.damp(look.pitch, look.targetPitch, 16, delta);
  camera.rotation.set(look.pitch, look.yaw, 0, 'YXZ');
}

function updateWalk(delta) {
  updateLook(delta);
  const forward = Number(keys.has('KeyW') || keys.has('ArrowUp') || touchMove.has('forward'))
    - Number(keys.has('KeyS') || keys.has('ArrowDown') || touchMove.has('back'));
  const strafe = Number(keys.has('KeyD') || keys.has('ArrowRight') || touchMove.has('right'))
    - Number(keys.has('KeyA') || keys.has('ArrowLeft') || touchMove.has('left'));
  const moving = forward !== 0 || strafe !== 0;

  if (moving) {
    const direction = camera.getWorldDirection(new THREE.Vector3());
    direction.y = 0;
    direction.normalize();
    const right = new THREE.Vector3().crossVectors(direction, new THREE.Vector3(0, 1, 0)).normalize();
    const length = Math.hypot(forward, strafe) || 1;
    const speed = keys.has('ShiftLeft') || keys.has('ShiftRight') || touchMove.has('run') ? RUN_SPEED : WALK_SPEED;
    const stepX = (direction.x * forward + right.x * strafe) / length * speed * delta;
    const stepZ = (direction.z * forward + right.z * strafe) / length * speed * delta;
    const slices = Math.max(1, Math.ceil(Math.hypot(stepX, stepZ) / 0.06));
    for (let index = 0; index < slices; index += 1) {
      tryMove(stepX / slices, stepZ / slices);
    }
    state.bobClock += delta * (speed > WALK_SPEED ? 13 : 9.5);
  }

  if (jumpRequested && state.grounded) {
    state.velocityY = 4.5;
    state.grounded = false;
  }
  jumpRequested = false;

  if (state.grounded) {
    const support = supportAt(camera.position.x, camera.position.z, state.footY + STEP_UP);
    if (support && support.max[1] >= state.footY - STEP_DOWN) {
      state.footY = support.max[1];
      state.velocityY = 0;
    } else {
      state.grounded = false;
    }
  }

  if (!state.grounded) {
    state.velocityY = Math.max(state.velocityY - GRAVITY * delta, -26);
    const next = state.footY + state.velocityY * delta;
    const landing = supportAt(camera.position.x, camera.position.z, state.footY + 0.03);
    if (state.velocityY <= 0 && landing && next <= landing.max[1] && landing.max[1] <= state.footY + 0.03) {
      state.footY = landing.max[1];
      state.velocityY = 0;
      state.grounded = true;
    } else {
      state.footY = next;
    }
    if (state.footY < -4) respawn();
  }

  const bob = moving && state.grounded ? Math.sin(state.bobClock) * 0.016 : 0;
  camera.position.y = state.footY + EYE + bob;

  const label = storeyLabelAt(camera.position.y);
  const next = `${label} · walking`;
  if (els.status.textContent !== next) els.status.textContent = next;
}

// ------------------------------------------------------------------ lighting
const DAY = {
  exposure: 0.88,
  hemi: 0.34,
  ambient: 0.14,
  sun: 1.9,
  fill: 0.22,
  env: 0.26,
  fog: '#b3c3cb',
  background: '#b3c3cb',
  hemiSky: '#cfe2ef',
  hemiGround: '#5f5a52',
};
const NIGHT = {
  exposure: 0.82,
  hemi: 0.07,
  ambient: 0.035,
  sun: 0.05,
  fill: 0.035,
  env: 0.045,
  fog: '#0b1015',
  background: '#0b1015',
  hemiSky: '#2e4560',
  hemiGround: '#0e1319',
};
const dayColor = new THREE.Color(DAY.fog);
const nightColor = new THREE.Color(NIGHT.fog);
const hemiSkyDay = new THREE.Color(DAY.hemiSky);
const hemiSkyNight = new THREE.Color(NIGHT.hemiSky);
const hemiGroundDay = new THREE.Color(DAY.hemiGround);
const hemiGroundNight = new THREE.Color(NIGHT.hemiGround);

function updateLighting(delta) {
  state.nightBlend = THREE.MathUtils.damp(state.nightBlend, state.nightTarget, 2.6, delta);
  state.lightBlend = THREE.MathUtils.damp(state.lightBlend, state.lightTarget, 3.4, delta);
  const t = state.nightBlend;

  renderer.toneMappingExposure = THREE.MathUtils.lerp(DAY.exposure, NIGHT.exposure, t);
  hemi.intensity = THREE.MathUtils.lerp(DAY.hemi, NIGHT.hemi, t);
  ambient.intensity = THREE.MathUtils.lerp(DAY.ambient, NIGHT.ambient, t);
  sun.intensity = THREE.MathUtils.lerp(DAY.sun, NIGHT.sun, t);
  fill.intensity = THREE.MathUtils.lerp(DAY.fill, NIGHT.fill, t);
  scene.environmentIntensity = THREE.MathUtils.lerp(DAY.env, NIGHT.env, t);
  hemi.color.copy(hemiSkyDay).lerp(hemiSkyNight, t);
  hemi.groundColor.copy(hemiGroundDay).lerp(hemiGroundNight, t);

  const fog = dayColor.clone().lerp(nightColor, t);
  scene.fog.color.copy(fog);
  scene.background.copy(fog);
  skyMaterial.uniforms.uNight.value = t;

  for (const light of luminaires) {
    light.intensity = light.userData.full * state.lightBlend;
    light.visible = state.lightBlend > 0.01;
  }
}

// ------------------------------------------------------------------ actions
function setTime(mode) {
  state.night = mode === 'night';
  state.nightTarget = state.night ? 1 : 0;
  if (state.night) setLights(true, false);
  else setLights(false, false);
  syncLightLabels();
  for (const button of document.querySelectorAll('[data-time]')) {
    button.classList.toggle('active', button.dataset.time === mode);
  }
}

function setLights(enabled, notify = true) {
  state.lightsOn = enabled;
  state.lightTarget = enabled ? 1 : 0;
  if (notify) syncLightLabels();
}

function syncLightLabels() {
  els.lightsButton.setAttribute('aria-pressed', String(state.lightsOn));
  els.lightsLabel.textContent = state.lightsOn ? 'Lights on' : 'Lights off';
}

for (const button of document.querySelectorAll('[data-time]')) {
  button.addEventListener('click', () => setTime(button.dataset.time));
}
els.lightsButton.addEventListener('click', () => setLights(!state.lightsOn));
els.walkButton.addEventListener('click', () => {
  if (state.mode === 'walk') exitWalk();
  else enterWalk();
});
$('#resume-button').addEventListener('click', () => {
  if (isTouch) els.resume.hidden = true;
  else requestLock();
});
$('#exit-button').addEventListener('click', () => exitWalk());
$('#fullscreen-button').addEventListener('click', async () => {
  try {
    if (!document.fullscreenElement) await document.documentElement.requestFullscreen();
    else await document.exitFullscreen();
  } catch (error) {
    console.warn('Fullscreen unavailable', error);
  }
});

// -------------------------------------------------------------------- resize
function resize() {
  const width = Math.max(1, els.viewport.clientWidth);
  const height = Math.max(1, els.viewport.clientHeight);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  renderer.setSize(width, height, false);
}
window.addEventListener('resize', resize);

// ---------------------------------------------------------------------- loop
let lastFrame = performance.now();

function animate(now = performance.now()) {
  requestAnimationFrame(animate);
  const delta = Math.min(Math.max((now - lastFrame) / 1000, 0), 0.08);
  lastFrame = now;

  if (state.mode === 'walk') {
    updateWalk(delta);
  } else {
    if (state.focusTween) {
      const { from, fromTarget, to, toTarget, start, duration } = state.focusTween;
      const k = Math.min(1, (performance.now() - start) / duration);
      const eased = 1 - Math.pow(1 - k, 3);
      camera.position.lerpVectors(from, to, eased);
      orbit.target.lerpVectors(fromTarget, toTarget, eased);
      if (k >= 1) state.focusTween = null;
    }
    orbit.update();
  }

  updateDoors(delta);
  updateLighting(delta);
  sky.position.copy(camera.position);
  renderer.render(scene, camera);
}

if (import.meta.env.DEV) {
  window.thau = { scene, camera, orbit, state, renderer };
}

resize();
syncLightLabels();
requestAnimationFrame(animate);
loadModel();
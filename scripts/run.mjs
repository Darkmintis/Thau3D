#!/usr/bin/env node
/**
 * One entry point for the whole project, run from the repo root.
 *
 *   node scripts/run.mjs setup    install the viewer and build the sample models
 *   node scripts/run.mjs model    rebuild the model only
 *   node scripts/run.mjs dev      build the model, then start the viewer
 *   node scripts/run.mjs build    production build of the viewer
 *
 * Works with pnpm, npm or yarn: it uses whichever package manager is present.
 */

import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VIEWER = path.join(ROOT, 'viewer');
const MODELS = path.join(VIEWER, 'public', 'models');
const EXAMPLES = [
  ['examples/housewalk/house.thau.json', 'house'],
  ['examples/hill-cabin/hill.thau.json', 'hill'],
];

const isWindows = process.platform === 'win32';

function run(command, args, options = {}) {
  const common = {
    cwd: options.cwd ?? ROOT,
    stdio: options.quiet ? 'pipe' : 'inherit',
    encoding: 'utf8',
  };
  // On Windows the package managers are .cmd shims, so they need a shell; pass one
  // pre-quoted command line rather than args to avoid the DEP0190 warning.
  const result = isWindows
    ? spawnSync([command, ...args.map(quote)].join(' '), { ...common, shell: true })
    : spawnSync(command, args, common);
  if (result.error) throw result.error;
  if (result.status !== 0 && !options.allowFailure) {
    if (options.quiet && result.stderr) process.stderr.write(result.stderr);
    process.exit(result.status ?? 1);
  }
  return result;
}

function quote(value) {
  return /[\s"]/.test(value) ? `"${value.replace(/"/g, '\\"')}"` : value;
}

function detectPackageManager() {
  for (const manager of ['pnpm', 'npm']) {
    const probe = run(manager, ['--version'], { quiet: true, allowFailure: true });
    if (probe.status === 0) return manager;
  }
  throw new Error('no package manager found: install pnpm (corepack enable) or npm');
}

function detectPython() {
  for (const candidate of ['python', 'python3', 'py']) {
    const probe = run(candidate, ['--version'], { quiet: true, allowFailure: true });
    if (probe.status === 0) return candidate;
  }
  throw new Error('python 3.10+ not found on PATH');
}

function installViewer() {
  const manager = detectPackageManager();
  console.log(`→ installing viewer dependencies with ${manager}`);
  const args = manager === 'pnpm' ? ['-C', 'viewer', 'install'] : ['--prefix', 'viewer', 'install'];
  run(manager, args);
}

function ensureViewerDependencies() {
  if (existsSync(path.join(VIEWER, 'node_modules', 'vite'))) return;
  installViewer();
}

function buildModels() {
  const python = detectPython();
  console.log('→ building models');
  for (const [spec, stem] of EXAMPLES) {
    run(python, ['-m', 'thau3d', 'build', spec, '--stem', stem, '-o', 'viewer/public/models']);
  }
}

function dev() {
  ensureViewerDependencies();
  buildModels();
  const manager = detectPackageManager();
  console.log('→ starting the viewer on http://localhost:5174');
  const args = manager === 'pnpm' ? ['-C', 'viewer', 'dev'] : ['--prefix', 'viewer', 'run', 'dev'];
  run(manager, args);
}

function buildViewer() {
  ensureViewerDependencies();
  buildModels();
  const manager = detectPackageManager();
  const args = manager === 'pnpm' ? ['-C', 'viewer', 'build'] : ['--prefix', 'viewer', 'run', 'build'];
  run(manager, args);
}

function setup() {
  const python = detectPython();
  const version = run(python, ['--version'], { quiet: true, allowFailure: true }).stdout.trim();
  console.log(`→ ${version}`);
  installViewer();
  buildModels();
  console.log('\nReady. Run:  pnpm dev   (or npm run dev)');
  console.log('Then open:  http://localhost:5174');
}

const command = process.argv[2] || 'dev';
const commands = { setup, model: buildModels, dev, build: buildViewer };

if (!commands[command]) {
  console.error(`unknown command "${command}"`);
  console.error('use one of: setup, model, dev, build');
  process.exit(1);
}

try {
  commands[command]();
} catch (error) {
  console.error(`\nerror: ${error.message}`);
  process.exit(1);
}

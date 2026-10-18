import { spawn, execFile } from 'node:child_process';
import { existsSync, copyFileSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseEnv } from 'node:util';
const root = fileURLToPath(new URL('../', import.meta.url));
const windows = process.platform === 'win32';
const npm = windows ? 'npm.cmd' : 'npm';
const python = process.env.KEEL_PYTHON || (windows ? 'python' : 'python3');
const children = new Set();
let stopping = false;
function settings(folder) {
  const filename = path.join(root, folder, '.env');
  return existsSync(filename) ? parseEnv(readFileSync(filename, 'utf8')) : {};
}
function environment(folder) {
  const env = { ...process.env, ...settings(folder) };
  if (folder === 'backend') {
    env.MARKET_AI_CODEBASE_PATH ||= path.join(root, 'ai');
    const venv = path.join(root, 'ai', '.venv', windows ? 'Scripts/python.exe' : 'bin/python');
    env.MARKET_AI_PYTHON ||= existsSync(venv) ? venv : python;
    // Cost gate uses exactly the same actor/database settings as the Python workers.
    for (const [key, value] of Object.entries(settings('ai'))) {
      if (key.startsWith('SCRAPER_') || key.startsWith('COST_GATE_') || key.startsWith('SCRAPE_COST_') || key.startsWith('CREDENTIAL_VAULT_')) env[key] ??= value;
    }
  }
  return env;
}
function run(command, args, folder) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd: path.join(root, folder), env: environment(folder),
      stdio: 'inherit', shell: windows && command === npm, detached: !windows });
    children.add(child);
    child.once('error', () => { children.delete(child); reject(new Error(`Could not start ${command}. Check its installation.`)); });
    child.once('exit', (code, signal) => {
      children.delete(child);
      if (stopping || signal === 'SIGINT' || signal === 'SIGTERM' || code === 0) resolve();
      else reject(new Error(`${folder || 'keel'} process exited with code ${code}.`));
    });
  });
}
function stop() {
  if (stopping) return;
  stopping = true;
  for (const child of children) {
    if (!child.pid) continue;
    if (windows) execFile('taskkill', ['/PID', String(child.pid), '/T', '/F'], () => {});
    else { try { process.kill(-child.pid, 'SIGTERM'); } catch { /* already stopped */ } }
  }
}
process.once('SIGINT', stop);
process.once('SIGTERM', stop);
try {
  const action = process.argv[2] || 'dev';
  if (['workers','dispatch'].includes(action)) {
    console.log('The custom competitor worker bridge is disabled. Store, ingestion and notification workers are separate.');
  } else if (action === 'setup') {
    for (const folder of ['', 'backend', 'frontend', 'ai']) {
      const destination = path.join(root, folder, '.env');
      if (!existsSync(destination)) copyFileSync(path.join(root, folder, '.env.example'), destination);
    }
    await run(npm, ['ci'], 'backend');
    await run(npm, ['ci'], 'frontend');
    console.log('Dependencies installed. Fill local environment settings before starting. No migrations or demo seeds were run.');
  } else if (action === 'setup-ai' || action === 'setup-store') {
    await run(python, ['-m', 'venv', '.venv'], 'ai');
    const executable = path.join(root, 'ai', '.venv', windows ? 'Scripts/python.exe' : 'bin/python');
    await run(executable, ['-m', 'pip', 'install', ...(action === 'setup-store' ? ['-r', 'requirements-connectors.txt'] : ['-r', 'src/ai/requirements.txt', '-r', 'src/market_scraper/requirements.txt'])], 'ai');
  } else if (action === 'dev') {
    await Promise.all([run(npm, ['run', 'dev'], 'backend'), run(npm, ['run', 'dev', '--', '--host', '127.0.0.1'], 'frontend')]);
  } else if (['backend', 'frontend', 'dispatch', 'ingestion', 'store-sync', 'platform-notifications', 'tenant-notifications'].includes(action)) {
    const folder = action === 'frontend' ? 'frontend' : 'backend';
    const script = ({ backend: 'dev', frontend: 'dev', dispatch: 'worker:market-tracking', ingestion: 'worker:data-ingestion', 'store-sync': 'worker:store-connectors', 'platform-notifications': 'worker:platform-notifications', 'tenant-notifications': 'worker:tenant-notifications' })[action];
    await run(npm, ['run', script], folder);
  } else if (['store-api', 'insights-api'].includes(action)) {
    const venv = path.join(root, 'ai', '.venv', windows ? 'Scripts/python.exe' : 'bin/python');
    await run(existsSync(venv) ? venv : python, ['-m','uvicorn',action === 'store-api' ? 'src.ai.connectors.app:app' : 'src.ai.insights.app:app','--host','127.0.0.1','--port',action === 'store-api' ? '8002' : '8001'], 'ai');
  } else throw new Error('Use setup, setup-ai, setup-store, dev, backend, frontend, workers, dispatch, ingestion, store-api, store-sync, insights-api, platform-notifications, or tenant-notifications.');
} catch (error) { console.error(error.message); process.exitCode = 1; stop(); }

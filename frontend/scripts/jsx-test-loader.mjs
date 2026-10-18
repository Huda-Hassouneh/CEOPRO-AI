import fs from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { transformWithOxc } from 'vite';

/** Test-only JSX/CSS loading using the frontend's existing Vite transformer. */
export async function load(url, context, nextLoad) {
  if (!url.startsWith('file:') || url.includes('/node_modules/')) return nextLoad(url, context);
  if (/\.(css|png|svg|woff2?|ttf)$/.test(url)) {
    return { format: 'module', source: `export default ${JSON.stringify(url)};`, shortCircuit: true };
  }
  if (/\.(jsx|js)$/.test(url)) {
    const filename = fileURLToPath(url);
    const source = (await fs.readFile(filename, 'utf8')).replaceAll('import.meta.env', '({ DEV: false, MODE: "test" })');
    const result = await transformWithOxc(source, filename, { jsx: { runtime: 'automatic' } });
    return { format: 'module', source: result.code, shortCircuit: true };
  }
  return nextLoad(url, context);
}

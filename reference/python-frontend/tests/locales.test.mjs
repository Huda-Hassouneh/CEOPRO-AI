// The English and Arabic translations stay in step, and every literal
// translation key used in the code exists - an untranslated key would show
// on screen as its dotted name.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const read = (path) => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const bundles = {
  app: { en: read('src/assets/locales/en.json'), ar: read('src/assets/locales/ar.json') },
  landing: { en: read('src/features/landing/locales/en.json'), ar: read('src/features/landing/locales/ar.json') },
};

function leaves(value, prefix = '', out = new Map()) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [key, child] of Object.entries(value)) leaves(child, prefix ? `${prefix}.${key}` : key, out);
  } else {
    out.set(prefix, value);
  }
  return out;
}

const placeholders = (text) => new Set(String(text).match(/\{\{\w+\}\}/g) || []);

for (const [name, { en, ar }] of Object.entries(bundles)) {
  test(`${name}: English and Arabic have the same keys`, () => {
    const enKeys = [...leaves(en).keys()];
    const arKeys = new Set(leaves(ar).keys());
    assert.deepEqual(enKeys.filter((k) => !arKeys.has(k)), [], 'missing in Arabic');
    assert.deepEqual([...arKeys].filter((k) => !leaves(en).has(k)), [], 'only in Arabic');
  });

  test(`${name}: no text blank in one language only, and both languages use the same {{placeholders}}`, () => {
    const arLeaves = leaves(ar);
    const problems = [];
    for (const [key, value] of leaves(en)) {
      const other = arLeaves.get(key);
      // A text may be deliberately blank (e.g. no caption), but only in both languages.
      if (typeof value === 'string' && typeof other === 'string' && !value.trim() !== !other.trim()) {
        problems.push(`${key}: blank in ${value.trim() ? 'Arabic' : 'English'} only`);
      }
      if (typeof value === 'string' && typeof other === 'string') {
        const a = [...placeholders(value)].sort().join();
        const b = [...placeholders(other)].sort().join();
        if (a !== b) problems.push(`${key}: ${a || '-'} vs ${b || '-'}`);
      }
    }
    assert.deepEqual(problems, []);
  });
}

test('every literal t("...") key used in the code exists in English', () => {
  const files = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir)) {
      const path = join(dir, entry);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(jsx?|mjs)$/.test(entry)) files.push(path);
    }
  };
  walk(new URL('../src', import.meta.url).pathname);
  const known = new Set([...leaves(bundles.app.en).keys(), ...[...leaves(bundles.landing.en).keys()].map((k) => `landing.${k}`)]);
  const prefixes = new Set([...known].flatMap((k) => k.split('.').map((_, i, parts) => parts.slice(0, i + 1).join('.'))));
  const missing = [];
  for (const file of files) {
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(/\bt\(\s*'([a-zA-Z][\w-]*(?:\.[\w-]+)+)'/g)) {
      const key = match[1];
      // Landing components translate within their own bundle (useLanding()).
      if (!known.has(key) && !known.has(`landing.${key}`) && !prefixes.has(key)) missing.push(`${file.split('/src/')[1]}: ${key}`);
    }
  }
  assert.deepEqual(missing, []);
});

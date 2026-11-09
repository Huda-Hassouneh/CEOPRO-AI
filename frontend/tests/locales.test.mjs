// The English and Arabic translations stay in step, and every literal
// translation key used in the code exists - an untranslated key would show
// on screen as its dotted name.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

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

  // The interpolator only fills {{name}}; a single-brace {name} would reach
  // the screen literally ("Verified {date}").
  test(`${name}: no single-brace {placeholder} that would show literally`, () => {
    const problems = [];
    for (const [lang, bundle] of Object.entries({ en, ar })) {
      for (const [key, value] of leaves(bundle)) {
        if (typeof value === 'string' && /(?<!\{)\{\w+\}(?!\})/.test(value)) problems.push(`${lang} ${key}: ${value}`);
      }
    }
    assert.deepEqual(problems, []);
  });

  // An Arabic text with no Arabic letters but an English phrase is an
  // untranslated copy (product and brand names alone are allowed).
  test(`${name}: Arabic texts are translated, not English copies`, () => {
    const problems = [];
    for (const [key, value] of leaves(ar)) {
      if (typeof value !== 'string' || /[؀-ۿ]/.test(value)) continue;
      const words = value.replace(/\{\{\w+\}\}/g, '').match(/[A-Za-z]{3,}/g) || [];
      const brandOnly = /^(KEEL|English|Excel|Word|Shopify|WooCommerce|PayPal|Stripe|Google( Pay| Analytics)?|Microsoft SQL Server)$/.test(value.trim());
      const singleToken = !/\s/.test(value.trim()); // an e-mail address or URL example
      if (words.length >= 3 && !brandOnly && !singleToken) problems.push(`${key}: ${value}`);
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
  walk(fileURLToPath(new URL('../src', import.meta.url)));
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

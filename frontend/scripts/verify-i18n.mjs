import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseSync } from 'vite';
import { en as adminEn, ar as adminAr } from '../src/features/platform-admin/locales/messages.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');
const json = relative => JSON.parse(read(relative));
export const resources = Object.fromEntries(['en', 'ar'].map(locale => [locale, {
  ...json(`src/assets/locales/${locale}.json`),
  landing: json(`src/features/landing/locales/${locale}.json`),
  platformAdmin: locale === 'en' ? adminEn : adminAr,
}]));
const flatten = (object, prefix = '') => Object.fromEntries(Object.entries(object).flatMap(([key, value]) =>
  value !== null && typeof value === 'object'
    ? Object.entries(flatten(value, `${prefix}${key}.`)) : [[`${prefix}${key}`, value]],
));
const flat = Object.fromEntries(Object.entries(resources).map(([locale, values]) => [locale, flatten(values)]));
const tokens = value => [...value.matchAll(/\{\{(\w+)\}\}/g)].map(match => match[1]).sort();
const files = directory => fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry =>
  entry.isDirectory() ? files(path.join(directory, entry.name)) : [path.join(directory, entry.name)],
);

export function verifyTranslations() {
  assert.deepEqual(Object.keys(flat.en).sort(), Object.keys(flat.ar).sort(), 'English and Arabic must have matching keys');
  for (const key of Object.keys(flat.en)) {
    for (const locale of ['en', 'ar']) {
      assert.equal(typeof flat[locale][key], 'string', `${locale}: ${key} must be text`);
      assert.ok(flat[locale][key].trim(), `${locale}: ${key} must not be blank`);
    }
    assert.deepEqual(tokens(flat.en[key]), tokens(flat.ar[key]), `${key}: interpolation placeholders must match`);
  }
  let calls = 0;
  // Brand wordmarks and the existing sample competitor name remain proper nouns.
  const properNames = new Set(['KEEL', 'KEEL ·', 'orange', 'Stripe']);
  const copyAttributes = new Set(['label', 'title', 'placeholder', 'aria-label', 'ariaLabel', 'alt', 'caption', 'hint', 'description', 'emptyMessage', 'message', 'closeLabel', 'loadingLabel', 'helperText']);
  for (const file of files(path.join(root, 'src')).filter(file => /\.(?:js|jsx)$/.test(file) && !file.includes(`${path.sep}locales${path.sep}`))) {
    const source = fs.readFileSync(file, 'utf8');
    const relative = path.relative(root, file).replaceAll(path.sep, '/');
    if (file.endsWith('.jsx')) {
      const parsed = parseSync(file, source);
      assert.equal(parsed.errors.length, 0, `${relative}: JSX could not be audited`);
      const visit = node => {
        if (!node || typeof node !== 'object') return;
        if (node.type === 'JSXText') {
          const text = node.value.replace(/\s+/g, ' ').trim();
          const words = text.replace(/&(?:#\d+|#x[\da-f]+|[a-z]+);/gi, '');
          if (/\p{L}/u.test(words)) assert.ok(properNames.has(text), `${relative}: unmapped JSX text: ${text}`);
        }
        if (node.type === 'JSXAttribute' && copyAttributes.has(node.name?.name)
          && ['Literal', 'StringLiteral'].includes(node.value?.type) && /\p{L}/u.test(node.value.value)) {
          const text = node.value.value;
          // Admin primitives accept resource keys and translate them internally.
          const adminKey = relative.includes('/platform-admin/') && typeof adminEn[text] === 'string';
          assert.ok(adminKey || properNames.has(text), `${relative}: unmapped ${node.name.name}: ${text}`);
        }
        for (const value of Object.values(node)) {
          if (Array.isArray(value)) value.forEach(visit);
          else if (value && typeof value === 'object') visit(value);
        }
      };
      visit(parsed.program);
    }
    const callsPattern = /\b(t|copyT|commonT|adminText|translateCurrent)\(\s*(['"])([^'"\r\n]+)\2|\b(tr|translate)\(\s*[^,\r\n]+,\s*(['"])([^'"\r\n]+)\5/g;
    for (const match of source.matchAll(callsPattern)) {
      // A literal prefix followed by + is a dynamic key, not a complete static key.
      if (source.slice(match.index + match[0].length).trimStart().startsWith('+')) continue;
      const name = match[1] || match[4];
      let key = match[3] || match[6];
      if (relative.includes('/landing/') && ['t', 'tr'].includes(name)) key = `landing.${key}`;
      if (relative.includes('/platform-admin/') && ['t', 'adminText'].includes(name)) key = `platformAdmin.${key}`;
      for (const locale of ['en', 'ar']) assert.equal(typeof flat[locale][key], 'string', `${relative}: missing ${locale} key ${key}`);
      calls++;
    }
  }
  return { keysPerLanguage: Object.keys(flat.en).length, staticCalls: calls };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const result = verifyTranslations();
  console.log(`Translation check passed: ${result.keysPerLanguage} keys per language; ${result.staticCalls} static calls; matching placeholders.`);
}

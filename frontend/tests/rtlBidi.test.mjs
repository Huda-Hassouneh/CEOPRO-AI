// Right-to-left and bidirectional-text regressions (docs/ARABIC_AI_QUALITY_REPORT.md).
// Arabic must reach the screen in Unicode logical order and be displayed by the browser's
// bidi algorithm - never reversed by hand - and user-entered text of unknown direction
// (product names, SKUs, imported rows) must be isolated so it cannot reorder its neighbours.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
let vite;
test.before(async () => { vite = await createServer({ root, server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' }); });
test.after(async () => { await vite.close(); });

function files(dir, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) files(full, out);
    else if (/\.(jsx?|json|css)$/.test(entry.name)) out.push(full);
  }
  return out;
}

test('Arabic locale is right-to-left and English left-to-right', async () => {
  const { getLocaleDirection } = await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  assert.equal(getLocaleDirection('ar'), 'rtl');
  assert.equal(getLocaleDirection('en'), 'ltr');
});

test('no source or translation fakes Arabic display order', () => {
  // Presentation-form glyphs (U+FB50-FDFF, U+FE70-FEFF) mean text was pre-shaped/reversed
  // for display; LRO/RLO overrides (U+202D/U+202E) force a reversed order. Both break
  // copy/paste, search and screen readers, so neither may appear in the UI sources.
  const offenders = [];
  for (const file of files(path.join(root, 'src'))) {
    const text = fs.readFileSync(file, 'utf8');
    if (/[\uFB50-\uFDFF\uFE70-\uFEFF\u202D\u202E]/.test(text.replace(/^\uFEFF/, ''))) offenders.push(path.relative(root, file));
  }
  assert.deepEqual(offenders, []);
});

test('the Arabic translations are stored in logical order (first letter first)', () => {
  const locales = files(path.join(root, 'src')).filter((f) => /[\\/]ar[^\\/]*\.json$/.test(f) || /[\\/]locales[\\/].*ar.*\.json$/.test(f));
  assert.ok(locales.length > 0, 'Arabic locale files exist');
  const sample = [];
  for (const file of locales) {
    const walk = (value) => {
      if (typeof value === 'string') sample.push(value);
      else if (value && typeof value === 'object') Object.values(value).forEach(walk);
    };
    walk(JSON.parse(fs.readFileSync(file, 'utf8')));
  }
  const arabic = sample.filter((s) => /[ء-ي]/.test(s));
  assert.ok(arabic.length > 100);
  // A word never starts with the final-only taa marbuta or alef maqsura in logical order;
  // reversed strings would put them first.
  const reversed = arabic.filter((s) => s.split(/\s+/).some((w) => /^[ةى][ء-ي]{2,}/.test(w)));
  assert.deepEqual(reversed, []);
});

test('every assistant answer block takes its direction from its own content (dir="auto")', async () => {
  const { AssistantResponse } = await vite.ssrLoadModule('/src/features/knowledge-base/components/AssistantResponse.jsx');
  const t = (key) => key;
  const claim = (text) => ({ text, kind: 'fact', verified: true, notes: [], refs: [] });
  const cited = renderToStaticMarkup(React.createElement(AssistantResponse, {
    blocks: [
      { type: 'heading', text: 'Delivery' },
      { type: 'paragraph', claims: [claim('سعر OL-1000 هو 8.90 دينار.')] },
      { type: 'paragraph', claims: [claim('Free delivery above 40 JOD.')] },
      { type: 'list', ordered: false, items: [[claim('التوصيل خلال ٤٨ ساعة.')]] },
    ], t,
  }));
  // An English paragraph inside the Arabic UI keeps its full stop on the right, and vice versa.
  assert.match(cited, /<h4 dir="auto">Delivery<\/h4>/);
  assert.equal((cited.match(/<p dir="auto">/g) || []).length, 2);
  assert.match(cited, /<li dir="auto">/);
  assert.ok(cited.includes('سعر OL-1000 هو 8.90 دينار.'), 'logical-order text is passed through untouched');
  const markdown = renderToStaticMarkup(React.createElement(AssistantResponse, {
    content: '## Prices\n\nThe price is 8.90 JOD.\n\n- زيت زيتون 1 لتر\n\n| المنتج | السعر |\n|---|---|\n| OL-1000 | 8.90 |', t,
  }));
  assert.match(markdown, /<p dir="auto">/);
  assert.match(markdown, /<li dir="auto">/);
  assert.match(markdown, /<td dir="auto">/);
});

test('imported product names are isolated in the import review', async () => {
  const { StructuredImportReview } = await vite.ssrLoadModule('/src/features/data-ingestion/components/StructuredImportReview.jsx');
  const t = (key, values) => (values && values.row ? `row ${values.row}` : key);
  const preview = {
    matches: [{ key: 'k1', status: 'missing', productName: 'Zaytouna Olive Oil 1L.', sku: 'OL-1000', candidates: [], sheet: 'items', row: 4 }],
    issues: [], sheets: ['items'], counts: { invoices: 0, items: 1, inventory: 0, matched: 0, needsAttention: 1 },
    canCreateProducts: true, primaryCurrency: 'JOD',
  };
  const review = { counts: { invoices: 0, items: 1, inventory: 1, productsToCreate: 1 }, changes: [{ key: 'c1', productName: 'زيت زيتون (Extra Virgin) 1L', next: 5 }] };
  const html = renderToStaticMarkup(React.createElement(StructuredImportReview, {
    preview, choices: {}, review, busy: false, onChoice() {}, onReview() {}, onConfirm() {}, onCancel() {}, locale: 'ar', t,
  }));
  assert.match(html, /<bdi>Zaytouna Olive Oil 1L\.<\/bdi>/);
  assert.match(html, /<bdi>زيت زيتون \(Extra Virgin\) 1L<\/bdi>/);
});

test('catalog and quick-sale product names are isolated', () => {
  const list = fs.readFileSync(path.join(root, 'src/features/products/pages/ProductsListPage.jsx'), 'utf8');
  const sale = fs.readFileSync(path.join(root, 'src/features/products/components/QuickSaleModal.jsx'), 'utf8');
  assert.match(list, /<bdi>\{product\.product_name\}<\/bdi><\/button>/);
  assert.match(sale, /<bdi>\{product\.product_name\}<\/bdi>/);
});

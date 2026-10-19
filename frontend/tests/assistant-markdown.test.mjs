import test from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown } from '../src/features/knowledge-base/utils/markdown.js';

test('a Markdown table from the model becomes a table block', () => {
  const blocks = parseMarkdown('Restock these:\n\n| Product | Stock |\n|---|---|\n| Dates | 95 |\n| Honey | 35 |\n\nSource: KEEL calculations.');
  assert.deepEqual(blocks.map((b) => b.type), ['paragraph', 'table', 'paragraph']);
  assert.deepEqual(blocks[1].head, ['Product', 'Stock']);
  assert.deepEqual(blocks[1].rows, [['Dates', '95'], ['Honey', '35']]);
});

test('bulleted and numbered lists are grouped', () => {
  const blocks = parseMarkdown('- one\n- two\n\n1. first\n2. second');
  assert.equal(blocks[0].type, 'list');
  assert.equal(blocks[0].ordered, false);
  assert.deepEqual(blocks[0].items, ['one', 'two']);
  assert.equal(blocks[1].ordered, true);
});

test('Arabic lines and a lone pipe character stay paragraphs', () => {
  const blocks = parseMarkdown('المنتجات | الأكثر مبيعًا\n### عنوان');
  assert.deepEqual(blocks, [{ type: 'paragraph', text: 'المنتجات | الأكثر مبيعًا' }, { type: 'heading', text: 'عنوان' }]);
});

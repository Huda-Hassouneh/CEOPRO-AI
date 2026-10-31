import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { mapAnswer } from '../src/features/knowledge-base/utils/references.js';

const locale = (lang) => JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`, import.meta.url), 'utf8'));

test('a conversational reply keeps its mode, its suggestions and has no references', () => {
  const mapped = mapAnswer({
    answer: 'هلا وغلا! كيف بقدر أساعدك اليوم؟', answer_mode: 'conversation', references: [], sources: [],
    answer_blocks: [{ type: 'paragraph', claims: [{ text: 'هلا وغلا! كيف بقدر أساعدك اليوم؟', kind: 'general', refs: [], verified: true, notes: [] }] }],
    follow_up_questions: ['كيف كانت مبيعاتي هالشهر؟', 'شو المنتجات اللي مخزونها قرب يخلص؟', 'مين منافسيني؟', 'extra'],
  });
  assert.equal(mapped.answerMode, 'conversation');
  assert.deepEqual(mapped.references, []);
  assert.equal(mapped.followUpQuestions.length, 3);
  assert.equal(mapped.blocks[0].claims[0].kind, 'general');
});

test('a general-knowledge answer keeps its mode and its guidance sentences', () => {
  const mapped = mapAnswer({
    answer: 'Gross margin is ...', answer_mode: 'general_knowledge', references: [],
    answer_blocks: [{ type: 'paragraph', claims: [{ text: 'Gross margin is the share of each sale left after paying for what you sold.', kind: 'guidance', refs: [], verified: true, notes: [] }] }],
  });
  assert.equal(mapped.answerMode, 'general_knowledge');
  assert.equal(mapped.blocks[0].claims[0].kind, 'guidance');
});

test('the general-knowledge note exists in English and Arabic', () => {
  for (const lang of ['en', 'ar']) {
    const note = locale(lang).ragAssistant.chat.generalKnowledgeNote;
    assert.ok(typeof note === 'string' && note.length > 10, `${lang} note missing`);
  }
  assert.match(locale('ar').ragAssistant.chat.generalKnowledgeNote, /[؀-ۿ]/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  mapAnswer, mapBlocks, mapReferences, referenceByNumber, safeExternalUrl, safeInternalRoute, statusNotes,
} from '../src/features/knowledge-base/utils/references.js';

const response = {
  answer: 'Revenue was 20,016.928 JOD.¹',
  answer_blocks: [
    { type: 'heading', text: 'Sales' },
    { type: 'paragraph', claims: [{ text: 'Revenue was 20,016.928 JOD.', kind: 'fact', refs: [1], verified: true, notes: [] }] },
    { type: 'list', ordered: false, items: [[{ text: 'Consider a promotion.', kind: 'recommendation', refs: [1, 2], verified: true, notes: [] }]] },
    { type: 'table', columns: ['Product', 'Revenue'], rows: [['Oil', '3078.95']], refs: [2] },
    { type: 'unknown-block' },
  ],
  references: [
    { n: 1, kind: 'company_record', title: 'Sales in the last 30 days', excerpt: 'Revenue 20016.928 JOD', route: '/sales', url: null, used_as: ['supports_fact'], limitations: [] },
    { n: 2, kind: 'web_page', title: 'Customs tariff', url: 'https://customs.gov.jo/tariff', route: null, credibility: 'official', jurisdiction: 'JO', published_at: '2026-01-01', used_as: ['supports_recommendation'] },
    { n: 3, kind: 'web_page', title: 'Bad link', url: 'javascript:alert(1)', route: '//evil.example' },
  ],
  follow_up_questions: ['And last quarter?', 'By product?', 'By store?', 'A fourth one'],
  evidence_status: [{ need: 'public_research', status: 'not_configured' }, { need: 'sales', status: 'not_permitted' }],
  answer_mode: 'ai',
};

test('an answer maps to claims, numbered references and follow-up questions', () => {
  const answer = mapAnswer(response);
  assert.equal(answer.blocks.length, 4, 'unknown block types are dropped');
  assert.deepEqual(answer.blocks[1].claims[0].refs, [1]);
  assert.equal(answer.blocks[2].items[0][0].kind, 'recommendation');
  assert.deepEqual(answer.blocks[3].refs, [2]);
  assert.equal(answer.references.length, 3);
  assert.equal(answer.followUpQuestions.length, 3, 'at most three follow-ups');
  assert.equal(answer.sources.length, 0, 'claim-level references replace the old source list');
});

test('reference links are limited to http(s) sources and in-app routes', () => {
  const refs = mapReferences(response.references);
  assert.equal(refs[0].route, '/sales');
  assert.equal(refs[1].url, 'https://customs.gov.jo/tariff');
  assert.equal(refs[1].jurisdiction, 'JO');
  assert.equal(refs[2].url, null, 'a javascript: link is never opened');
  assert.equal(refs[2].route, null, 'a protocol-relative route is not an in-app route');
  assert.equal(safeExternalUrl('ftp://example.com/x'), null);
  assert.equal(safeInternalRoute('/products/123'), '/products/123');
  assert.equal(referenceByNumber(refs, 2).title, 'Customs tariff');
  assert.equal(referenceByNumber(refs, 9), null);
});

test('answers saved before references existed keep their source list', () => {
  const answer = mapAnswer({ answer: 'Old answer', sources: [{ url: 'https://example.com', title: 'Example' }, { source_index: 1, chunk_id: 'c1' }] });
  assert.equal(answer.blocks, null);
  assert.equal(answer.references.length, 0);
  assert.equal(answer.sources[0].sourceType, 'web');
  assert.equal(answer.sources[1].sourceType, 'knowledge-base');
  assert.equal(answer.content, 'Old answer');
});

test('evidence states become notes the user can read, never silent', () => {
  assert.deepEqual(statusNotes(response.evidence_status), ['researchNotConfigured', 'notPermitted']);
  assert.deepEqual(statusNotes([{ need: 'landed_cost_calculation', status: 'missing_inputs' }]), ['calculationMissing']);
  assert.deepEqual(statusNotes([{ need: 'public_research', status: 'found' }]), []);
  assert.deepEqual(statusNotes([{ need: 'answer_writing', status: 'not_configured' }]), ['answerNotConfigured']);
  assert.deepEqual(statusNotes([{ need: 'answer_writing', status: 'provider_busy' }]), [], 'a busy provider is temporary, not an admin task');
});

test('claims keep their kind and verification state', () => {
  const blocks = mapBlocks([{ type: 'paragraph', claims: [{ text: 'x', kind: 'fact', refs: ['1', 2], verified: false, notes: ['no_evidence'] }, 'plain']}]);
  assert.deepEqual(blocks[0].claims[0].refs, [2], 'only integer reference numbers are kept');
  assert.equal(blocks[0].claims[0].verified, false);
  assert.equal(blocks[0].claims[1].kind, 'general');
  assert.equal(mapBlocks([]), null);
});

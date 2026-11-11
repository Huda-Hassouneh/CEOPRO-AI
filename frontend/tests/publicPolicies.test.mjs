import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { PUBLIC_POLICIES, POLICY_APPROVED, POLICY_EFFECTIVE_DATE, parsePolicyMarkdown, policyCopy } from '../src/features/legal/policyCatalog.js';

test('public candidates have no fabricated approval or effective date', () => {
  assert.equal(POLICY_APPROVED, false);
  assert.equal(POLICY_EFFECTIVE_DATE, null);
  assert.equal(new Set(PUBLIC_POLICIES.map(p => p.path)).size, 6);
  assert.deepEqual(PUBLIC_POLICIES.map(p => p.path), ['/terms', '/privacy', '/refund-policy', '/subscription-policy', '/trial-renewal', '/contact']);
});
test('all five policy documents exist in both languages and retain unresolved legal decisions', () => {
  for (const lang of ['en', 'ar']) {
    for (const policy of PUBLIC_POLICIES.filter(p => p.kind !== 'contact')) {
      const text = readFileSync(new URL(`../src/features/legal/content/${lang}/${policy.kind}.md`, import.meta.url), 'utf8');
      assert.ok(text.length > 500);
      assert.match(text, /\[\[[A-Z0-9_]+\]\]/);
      assert.ok(policy[lang]);
      assert.ok(parsePolicyMarkdown(text).length > 1);
    }
    assert.ok(policyCopy[lang].draft);
  }
});
test('renderer model preserves untrusted HTML as text and does not interpret scripts', () => {
  const blocks = parsePolicyMarkdown('# Title\n\n## Heading\n<script>alert(1)</script>\n\n- [[UNAPPROVED_FIELD]]');
  assert.equal(blocks[0].body, '<script>alert(1)</script>');
  assert.equal(blocks[1].type, 'list');
});
test('Paddle Sandbox-only approval and 30-day test retention do not become public commitments', () => {
  for (const lang of ['en', 'ar']) {
    const privacy = readFileSync(new URL(`../src/features/legal/content/${lang}/privacy.md`, import.meta.url), 'utf8');
    assert.match(privacy, /\[\[APPROVED_RETENTION_SCHEDULE\]\]/);
    assert.doesNotMatch(privacy, /keel-sandbox-2026|30 days after|900-second/);
  }
});

test('approved Standard trial policy is bilingual and legacy access is not represented as recurring consent', () => {
  for (const lang of ['en', 'ar']) {
    const text = readFileSync(new URL(`../src/features/legal/content/${lang}/subscriptions.md`, import.meta.url), 'utf8');
    assert.match(text, /Standard/);
    assert.match(text, /Plus/);
    assert.match(text, /Pro/);
    assert.match(text, /14/);
    assert.doesNotMatch(text, /seven-day|سبعة أيام/);
    assert.match(text, lang === 'en' ? /legacy local signup trial/ : /تجربة التسجيل المحلية/);
    assert.ok(policyCopy[lang].trialPolicy);
    assert.ok(policyCopy[lang].periods.monthly);
  }
});

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { competitorsApi } from '../src/features/market-intelligence/api/competitorsApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// competitorsApi.profile() now calls the real, mounted
// backend/src/ai/routers/competitors.py GET /competitors/{id} - previously
// there was no such endpoint server-side at all, so this always returned
// {id, competitor: null}. Same http.createServer contract-test technique
// as tests/settings.test.mjs / tests/forecasting.test.mjs.
test('competitorsApi.profile sends the real request and honestly reports a 404 as competitor: null', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/competitors/c1') {
      return res.end(JSON.stringify({
        id: 'c1', name: 'Rival Co', tier: 'STRATEGIC', website_url: 'https://rival.jo',
        market_sentiment_label: 'Positive', price_competitiveness: 7.2, last_updated: '2026-09-01T00:00:00Z',
        market_activity: 'High', relevance_score: 81.4, strengths: ['Positive customer sentiment'], weaknesses: [],
        summary_line: 'Strategic competitor — 62% product overlap with your catalog.', overlap_pct: 62.0,
      }));
    }
    if (req.url === '/competitors/missing') {
      res.statusCode = 404;
      return res.end(JSON.stringify({ detail: 'Competitor not found' }));
    }
    res.statusCode = 500;
    res.end(JSON.stringify({ detail: 'unexpected' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const found = await competitorsApi.profile('c1');
  assert.equal(found.competitor.name, 'Rival Co');
  assert.equal(found.competitor.tier, 'STRATEGIC');
  assert.equal(found.competitor.overlap_pct, 62.0);

  const notFound = await competitorsApi.profile('missing');
  assert.equal(notFound.competitor, null);
  assert.equal(notFound.id, 'missing');
});

test('competitor summary and traits render from language-neutral fields, falling back to the English text', async () => {
  const { competitorSummary, competitorTraits } = await import('../src/features/market-intelligence/api/competitorsApi.js');
  const dict = {
    'market.competitorsPage.summaryStrategic': 'استراتيجي {{pct}}٪',
    'market.competitorsPage.summaryRelevant': 'ذو صلة {{count}}',
    'market.traits.SENTIMENT_POSITIVE': 'آراء إيجابية',
  };
  const t = (key, params = {}) => (dict[key] ?? key).replace(/\{\{(\w+)\}\}/g, (_, name) => params[name]);

  assert.equal(competitorSummary(t, { tier: 'STRATEGIC', product_overlap_pct: 61.6, summary_line: 'Strategic competitor — 62%' }), 'استراتيجي 62٪');
  assert.equal(competitorSummary(t, { tier: 'RELEVANT', matched_product_count: 3, summary_line: 'x' }), 'ذو صلة 3');
  assert.equal(competitorSummary(t, { tier: 'RELEVANT', summary_line: 'Relevant competitor — 3' }), 'Relevant competitor — 3');
  assert.deepEqual(competitorTraits(t, ['SENTIMENT_POSITIVE', 'NEW_CODE'], ['Positive customer sentiment', 'Something new']), ['آراء إيجابية', 'Something new']);
  assert.deepEqual(competitorTraits(t, undefined, ['Positive customer sentiment']), ['Positive customer sentiment']);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { sourceReviewApi } from '../src/features/market-intelligence/api/sourceReviewApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// sourceReviewApi wraps the real, mounted backend/src/ai/routers/
// competitors.py GET/POST /competitors/sources[...] endpoints, themselves
// a thin wrapper around source_review.py::review_source() - this test
// verifies the request/response shape actually matches what that backend
// router sends and expects, not a mocked assumption.

function withServer(handler) {
  return async (t) => {
    const server = http.createServer(handler);
    await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
    const originalBaseURL = httpClient.defaults.baseURL;
    httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
    t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });
  };
}

test('sourceReviewApi.listSources returns the real sources+counts shape', async (t) => {
  await withServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url.startsWith('/competitors/sources') && req.method === 'GET') {
      return res.end(JSON.stringify({
        sources: [{
          source_id: 's1', source_name: 'Real Competitor', source_url: 'https://real-competitor.example/p',
          collection_method: 'WEB_SCRAPE', policy_status: 'RESTRICTED', collector_key: 'standards',
          created_at: '2026-09-29T00:00:00', approval_reference: null, approved_at: null,
          competitor_name: 'Real Competitor', global_competitor_id: 'c1', mapped_product_count: 1,
        }],
        counts: { ALLOWED: 0, RESTRICTED: 1, BLOCKED: 0 },
      }));
    }
    res.statusCode = 404;
    res.end('{}');
  })(t);

  const result = await sourceReviewApi.listSources({ status: 'RESTRICTED' });
  assert.equal(result.sources.length, 1);
  assert.equal(result.sources[0].policy_status, 'RESTRICTED');
  assert.equal(result.counts.RESTRICTED, 1);
});

test('sourceReviewApi.listSources passes status/limit/offset as real query params', async (t) => {
  let receivedUrl;
  await withServer((req, res) => {
    receivedUrl = req.url;
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ sources: [], counts: { ALLOWED: 0, RESTRICTED: 0, BLOCKED: 0 } }));
  })(t);

  await sourceReviewApi.listSources({ status: 'BLOCKED', limit: 10, offset: 20 });
  const params = new URL(receivedUrl, 'http://localhost').searchParams;
  assert.equal(params.get('status'), 'BLOCKED');
  assert.equal(params.get('limit'), '10');
  assert.equal(params.get('offset'), '20');
});

test('sourceReviewApi.reviewSource sends the real snake_case body and returns the review result', async (t) => {
  let received;
  await withServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/competitors/sources/s1/review' && req.method === 'POST') {
      let body = '';
      req.on('data', (chunk) => { body += chunk; });
      req.on('end', () => {
        received = JSON.parse(body);
        res.end(JSON.stringify({
          source_id: 's1', status: 'ALLOWED', method: 'WEB_SCRAPE', justification: 'ok',
          enqueued: true, enqueue_error: null,
        }));
      });
      return;
    }
    res.statusCode = 404;
    res.end('{}');
  })(t);

  const result = await sourceReviewApi.reviewSource('s1', {
    termsPermit: true, reviewerReference: 'Checked /terms - public catalog.',
  });
  assert.equal(received.terms_permit, true);
  assert.equal(received.reviewer_reference, 'Checked /terms - public catalog.');
  assert.equal(result.status, 'ALLOWED');
  assert.equal(result.enqueued, true);
});

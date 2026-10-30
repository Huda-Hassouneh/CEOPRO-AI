import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { importDraftsApi, describeImportApiError, importDraftStateKey } from '../src/features/data-ingestion/api/importDraftsApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('import drafts API uses the implemented list, revision, history and review contracts', async (t) => {
  const requests = [];
  const server = http.createServer((req, res) => {
    let body = '';
    req.on('data', (part) => { body += part; });
    req.on('end', () => {
      requests.push({ method: req.method, url: req.url, body: body ? JSON.parse(body) : null });
      res.setHeader('Content-Type', 'application/json');
      if (req.method === 'GET') res.end(JSON.stringify({ items: [] }));
      else res.end(JSON.stringify({ decision_id: 'decision-1', duplicate: false, canonical_write_performed: false }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  await importDraftsApi.list({ limit: 10, offset: 20, category: 'invoice' });
  await importDraftsApi.detail('batch/1');
  await importDraftsApi.detail('batch-1', 'revision-1');
  await importDraftsApi.revisions('batch-1');
  await importDraftsApi.reviews('batch-1', 'revision-1');
  const decision = { revision_id: 'revision-1', decision: 'approve', reason_code: 'checked', idempotency_key: 'retry-1', row_id: 'row-1' };
  const result = await importDraftsApi.decide('batch-1', decision);

  assert.equal(requests[0].url, '/extraction/import-drafts?limit=10&offset=20&category=invoice');
  assert.equal(requests[1].url, '/extraction/import-drafts/batch%2F1');
  assert.equal(requests[2].url, '/extraction/import-drafts/batch-1/revisions/revision-1');
  assert.equal(requests[3].url, '/extraction/import-drafts/batch-1/revisions');
  assert.equal(requests[4].url, '/extraction/import-drafts/batch-1/reviews?revision_id=revision-1');
  assert.equal(requests[5].method, 'POST');
  assert.deepEqual(requests[5].body, decision);
  assert.equal(result.canonical_write_performed, false);
});

test('draft error copy distinguishes authentication, authorization, missing and stale records', () => {
  const t = (key) => key;
  assert.match(describeImportApiError({ response: { status: 401 } }, t), /unauthorized$/);
  assert.match(describeImportApiError({ response: { status: 403 } }, t), /forbidden$/);
  assert.match(describeImportApiError({ response: { status: 404 } }, t), /notFound$/);
  assert.match(describeImportApiError({ response: { status: 409 } }, t), /conflict$/);
  assert.equal(importDraftStateKey('review_required'), 'connectData.drafts.states.review_required');
});

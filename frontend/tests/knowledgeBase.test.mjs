import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { knowledgeBaseApi } from '../src/features/knowledge-base/api/knowledgeBaseApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// api/knowledgeBaseApi.js calls the real, mounted backend/src/ai/routers/
// rag.py's POST /rag/query, GET /rag/sessions and GET /rag/sessions/{id}/
// messages (backend contract correctness - retrieval, answer generation,
// citation shape, RLS-scoped persistence - is covered by the backend's own
// pytest suite, not re-tested here). What's worth a local test with no
// backend running: that the api layer sends the real request shape
// (including the session_id param, once known) and maps the real response
// shape into what the UI consumes - same http.createServer technique as
// tests/marketing.test.mjs.
test('knowledge base api creates a session on the first turn and reuses it on follow-ups', async (t) => {
  const SESSION_ID = 'session-abc-123';
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');

    if (url.pathname === '/rag/query' && req.method === 'POST') {
      const queryText = url.searchParams.get('query_text');
      const sessionId = url.searchParams.get('session_id');

      if (queryText === 'first question') {
        // The very first turn has no known session yet - session_id must
        // be omitted entirely, never sent as an empty string (the backend
        // treats an omitted param as "start a new session").
        assert.equal(sessionId, null);
        return res.end(JSON.stringify({
          answer: 'First answer.',
          sources: [{ source_index: 1, chunk_id: 'c1', score: 0.9 }],
          session_id: SESSION_ID,
        }));
      }

      if (queryText === 'follow-up question') {
        // Once a session exists, every subsequent turn must reuse its
        // real session_id - the backend loads persisted history from it,
        // it does not accept client-supplied history anymore.
        assert.equal(sessionId, SESSION_ID);
        return res.end(JSON.stringify({
          answer: 'Follow-up answer, based on a web search.',
          sources: [{ url: 'https://example.com/article', title: 'Example Article' }],
          session_id: SESSION_ID,
        }));
      }
    }

    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const capabilities = await knowledgeBaseApi.getCapabilities();
  assert.equal(capabilities.conversationHistory, true);

  const first = await knowledgeBaseApi.chat({ question: 'first question' });
  assert.equal(first.available, true);
  assert.equal(first.sessionId, SESSION_ID);
  assert.equal(first.message.content, 'First answer.');
  assert.equal(first.message.sources[0].sourceType, 'knowledge-base');
  assert.equal(first.message.sources[0].citationId, 'c1');

  // The real session id a chat page would have captured and remembered
  // after that first turn - passed straight through on the next call.
  const second = await knowledgeBaseApi.chat({ question: 'follow-up question', sessionId: first.sessionId });
  assert.equal(second.available, true);
  assert.equal(second.sessionId, SESSION_ID);
  assert.equal(second.message.content, 'Follow-up answer, based on a web search.');
  // A web-fallback source is distinguished from a chunk citation by
  // carrying a real, clickable uri - never invented.
  assert.equal(second.message.sources[0].uri, 'https://example.com/article');
  // Business Copilot Phase 2 (B8/B10/B14): a web source must be labeled
  // 'web', not 'knowledge-base' - the SourceCitationList UI relies on
  // this to render a distinct "external web source" badge and never
  // present external content as if it were the tenant's own KEEL data.
  assert.equal(second.message.sources[0].sourceType, 'web');
});

test('knowledge base api lists sessions and restores a session\'s messages for a page-refresh restore', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    const url = new URL(req.url, 'http://localhost');

    if (url.pathname === '/rag/sessions' && req.method === 'GET') {
      return res.end(JSON.stringify({
        sessions: [
          { session_id: 's1', title: 'first question', created_at: '2026-09-25T10:00:00Z', updated_at: '2026-09-25T10:05:00Z' },
        ],
      }));
    }

    if (url.pathname === '/rag/sessions/s1/messages' && req.method === 'GET') {
      return res.end(JSON.stringify({
        session_id: 's1',
        messages: [
          { message_id: 'm1', role: 'user', content: 'first question', sources: [], created_at: '2026-09-25T10:00:00Z' },
          { message_id: 'm2', role: 'assistant', content: 'First answer.', sources: [{ chunk_id: 'c1', score: 0.9 }], created_at: '2026-09-25T10:00:01Z' },
        ],
      }));
    }

    if (url.pathname === '/rag/sessions/missing/messages' && req.method === 'GET') {
      res.statusCode = 404;
      return res.end(JSON.stringify({ detail: 'Conversation session not found.' }));
    }

    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const sessions = await knowledgeBaseApi.listSessions();
  assert.equal(sessions.available, true);
  assert.equal(sessions.sessions.length, 1);
  assert.equal(sessions.sessions[0].session_id, 's1');

  const restored = await knowledgeBaseApi.getSessionMessages('s1');
  assert.equal(restored.available, true);
  assert.equal(restored.messages.length, 2);
  assert.equal(restored.messages[0].role, 'user');
  assert.equal(restored.messages[1].sources[0].citationId, 'c1');

  // A session id that doesn't resolve (deleted, wrong tenant/user) must be
  // "nothing to restore", never a thrown error the page has to catch.
  const missing = await knowledgeBaseApi.getSessionMessages('missing');
  assert.equal(missing.available, false);
  assert.deepEqual(missing.messages, []);
});

test('mapDocuments exposes real uploaded documents with their processing status', async () => {
  const { mapDocuments } = await import('../src/features/knowledge-base/api/knowledgeBaseApi.js');
  const docs = mapDocuments({ documents: [
    { document_id: 'd1', file_name: 'Return policy.pdf', type: 'pdf', size_bytes: 2048, uploaded_at: '2026-10-06T08:00:00+00:00', status: 'ready', chunk_count: 3 },
  ] });
  assert.deepEqual(docs, [{ id: 'd1', name: 'Return policy.pdf', type: 'pdf', size: 2048, uploadedAt: '2026-10-06T08:00:00+00:00', status: 'ready', chunkCount: 3 }]);
  assert.deepEqual(mapDocuments(undefined), []);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import httpClient, { configureHttpClientAuth } from '../src/shared/lib/httpClient.js';

// Regression test for the "dashboard (and every other protected page)
// shows a generic 'unavailable' error forever after a token expires"
// bug: httpClient previously had no response interceptor at all, so a
// stale/expired/invalid token just kept getting 401 on every request
// with nothing clearing the (stale) local "authenticated" session or
// redirecting to /login. Verifies the fix directly: any 401 response
// invokes the configured onUnauthorized callback exactly once; other
// statuses (200, a real 404/500 on some other endpoint) never do.
test('httpClient invokes onUnauthorized on a real 401 and never on other statuses', async (t) => {
  const server = http.createServer((req, res) => {
    res.setHeader('Content-Type', 'application/json');
    if (req.url === '/needs-auth') {
      res.statusCode = 401;
      return res.end(JSON.stringify({ detail: 'Missing or malformed Authorization header.' }));
    }
    if (req.url === '/not-found') {
      res.statusCode = 404;
      return res.end(JSON.stringify({ detail: 'not found' }));
    }
    return res.end(JSON.stringify({ ok: true }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); configureHttpClientAuth({}); });

  let unauthorizedCalls = 0;
  configureHttpClientAuth({ getAccessToken: () => 'stale-token', onUnauthorized: () => { unauthorizedCalls += 1; } });

  await httpClient.get('/ok');
  assert.equal(unauthorizedCalls, 0);

  await assert.rejects(() => httpClient.get('/not-found'));
  assert.equal(unauthorizedCalls, 0, '404 must never be treated as a session expiry');

  await assert.rejects(() => httpClient.get('/needs-auth'));
  assert.equal(unauthorizedCalls, 1);

  await assert.rejects(() => httpClient.get('/needs-auth'));
  assert.equal(unauthorizedCalls, 2, 'every distinct 401 should still clear the session, not just the first one');
});

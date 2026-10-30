import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mpiApi } from '../src/features/market-intelligence/api/mpiApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('MPI API requests authenticated summary for each supported scope', async (t) => {
  const seen = [];
  const server = http.createServer((req, res) => {
    seen.push(req.url);
    res.setHeader('Content-Type', 'application/json');
    res.end(JSON.stringify({ status: 'UNKNOWN', sample_size: { analyzed_count: 0 } }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const baseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = baseURL; server.close(); });

  await mpiApi.summary({ subjectType: 'BUSINESS' });
  await mpiApi.summary({ subjectType: 'PRODUCT', subjectId: 'product-id' });
  await mpiApi.summary({ subjectType: 'COMPETITOR', subjectId: 'competitor-id' });
  assert.deepEqual(seen, [
    '/mpi/summary?subject_type=BUSINESS',
    '/mpi/summary?subject_type=PRODUCT&subject_id=product-id',
    '/mpi/summary?subject_type=COMPETITOR&subject_id=competitor-id',
  ]);
});

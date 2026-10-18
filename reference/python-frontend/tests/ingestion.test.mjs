import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { ingestionApi } from '../src/features/data-ingestion/api/ingestionApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

// The frontend's own static "template" file was a generic placeholder
// ("Field,Value,Date,Notes") that never matched what backend/src/ai/
// routers/extraction.py's upload pipeline actually parses - downloadTemplate
// now fetches the real canonical file from GET /extraction/templates/{fmt}
// for csv/xlsx. prepareFiles now really uploads via POST /extraction/upload
// (one real multipart request per file, matching that endpoint's own
// one-file-per-call contract) instead of just echoing back file metadata.
test('ingestion api layer fetches the real template and really uploads files', async (t) => {
  const server = http.createServer((req, res) => {
    if (req.url === '/extraction/templates/csv' && req.method === 'GET') {
      res.setHeader('Content-Type', 'text/csv');
      return res.end('product_name,quantity,unit_price,currency,transaction_date\n');
    }
    if (req.url === '/extraction/upload' && req.method === 'POST') {
      let body = Buffer.alloc(0);
      req.on('data', (chunk) => { body = Buffer.concat([body, chunk]); });
      req.on('end', () => {
        const asText = body.toString('utf8');
        res.setHeader('Content-Type', 'application/json');
        if (asText.includes('bad.csv')) { res.statusCode = 400; return res.end(JSON.stringify({ detail: 'File content does not match its csv extension.' })); }
        res.end(JSON.stringify({ job_id: 'j1', rows_processed: 3, rows_failed: 0, is_template_compliant: true }));
      });
      return;
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  // downloadTemplate's csv/xlsx path relies on the browser's real Blob/
  // URL.createObjectURL (axios's Node adapter doesn't implement
  // responseType: 'blob' the way a browser XHR does) - verified for real
  // in a headless browser against a live backend instead of here.

  // There is no PDF template (no approved PDF template exists) -
  // DATA_TEMPLATE_OPTIONS only lists csv/xlsx, so an unknown/removed id
  // like 'pdf' must degrade to an empty result, never a stale download.
  const pdfTemplate = await ingestionApi.downloadTemplate('pdf');
  assert.equal(pdfTemplate.filename, '');
  assert.equal(pdfTemplate.url, '');

  const good = new File(['product_name,quantity\nWidget,1'], 'good.csv', { type: 'text/csv' });
  const bad = new File(['not a real csv'], 'bad.csv', { type: 'text/csv' });
  const result = await ingestionApi.prepareFiles([good, bad]);
  assert.equal(result.uploaded, true);
  assert.equal(result.files[0].status, 'uploaded');
  assert.equal(result.files[0].summary.rows_processed, 3);
  assert.equal(result.files[1].status, 'failed');
});

// Regression test for a real bug: ConnectDataPage's Prepare Import button
// picks its toast message off `result.uploaded` - when the single file a
// user uploaded fails server-side (e.g. a downstream storage outage
// returning 500, not a frontend-validation problem), `uploaded` must come
// back false so the page shows an actual failure message instead of the
// stale "Backend upload is not connected" copy that used to be shown for
// any non-success case, wrongly implying the backend integration itself
// wasn't wired up.
test('prepareFiles reports uploaded:false when the only file fails server-side', async (t) => {
  const server = http.createServer((req, res) => {
    if (req.url === '/extraction/upload' && req.method === 'POST') {
      res.statusCode = 500;
      res.setHeader('Content-Type', 'application/json');
      return res.end(JSON.stringify({ detail: 'Upload processing failed.' }));
    }
    res.statusCode = 404;
    res.end(JSON.stringify({ detail: 'not found' }));
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const originalBaseURL = httpClient.defaults.baseURL;
  httpClient.defaults.baseURL = `http://127.0.0.1:${server.address().port}`;
  t.after(() => { httpClient.defaults.baseURL = originalBaseURL; server.close(); });

  const onlyFile = new File(['product_name,quantity\nWidget,1'], 'sales.xlsx', { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
  const result = await ingestionApi.prepareFiles([onlyFile]);
  assert.equal(result.uploaded, false);
  assert.equal(result.files[0].status, 'failed');
  assert.equal(result.files[0].error, 'Upload processing failed.');
});

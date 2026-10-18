import test from 'node:test';
import assert from 'node:assert/strict';
import { summarizeImport } from '../src/features/data-ingestion/utils/importSummary.js';

const t = (key, params = {}) => `${key}${JSON.stringify(params)}`;
const uploaded = (name, promotion) => ({ name, status: 'uploaded', summary: { promotion } });

// The page used to say "Files uploaded successfully." for any accepted file -
// no row counts, nothing about failed/duplicate rows or rejected files.
test('a clean import reports how many rows landed', () => {
  const { variant, message } = summarizeImport([uploaded('sales.csv', { rows_promoted: 1610, rows_duplicate: 0, rows_failed: 0 })], t);
  assert.equal(variant, 'success');
  assert.match(message, /sales\.csv/);
  assert.match(message, /importSummary\.imported\{"count":"1610"\}/);
  assert.doesNotMatch(message, /duplicates|failed/);
});

test('a re-uploaded file reports the rows skipped as already imported', () => {
  const { variant, message } = summarizeImport([uploaded('sales.csv', { rows_promoted: 0, rows_duplicate: 1610, rows_failed: 0 })], t);
  assert.equal(variant, 'info');
  assert.match(message, /importSummary\.duplicates\{"count":"1610"\}/);
});

test('row failures and rejected files are surfaced, not hidden behind a success message', () => {
  const partial = summarizeImport([uploaded('a.csv', { rows_promoted: 5, rows_failed: 2, rows_skipped_incomplete: 1 })], t);
  assert.equal(partial.variant, 'warning');
  assert.match(partial.message, /importSummary\.failed\{"count":"3"\}/);

  const mixed = summarizeImport([uploaded('a.csv', { rows_promoted: 5 }), { name: 'b.pdf', status: 'failed', error: 'Unsupported' }], t);
  assert.equal(mixed.variant, 'warning');
  assert.match(mixed.message, /b\.pdf/);

  const allFailed = summarizeImport([{ name: 'b.pdf', status: 'failed', error: 'Unsupported' }], t);
  assert.equal(allFailed.variant, 'error');
});

test('rows that failed before promotion are reported as failed, not silently dropped', () => {
  const result = summarizeImport([{ name: 'sales.xlsx', status: 'uploaded', summary: { rows_failed: 4573, promotion: { rows_promoted: 0 } } }], (key, values) => `${key}:${values?.count ?? ''}`);
  assert.equal(result.variant, 'error');
  assert.match(result.message, /importSummary\.failed:4573/);
});

test('rows over the plan product limit are reported as such, not as unreadable rows', () => {
  const { variant, message } = summarizeImport([uploaded('big.csv', { rows_promoted: 40, rows_failed: 7, rows_over_product_limit: 5 })], t);
  assert.equal(variant, 'warning');
  assert.match(message, /importSummary\.overProductLimit\{"count":"5"\}/);
  assert.match(message, /importSummary\.failed\{"count":"2"\}/);
});

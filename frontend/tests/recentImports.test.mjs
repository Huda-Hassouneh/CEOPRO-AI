import test from 'node:test';
import assert from 'node:assert/strict';
import { mapRecentImports } from '../src/features/data-connections/api/dataConnectionsApi.js';

// Connect Data's "Recent Data Activity" table used to be a hard-coded empty
// list, so it said "No recent data activity" even after real imports.

test('maps real import jobs to table rows with the uploaded file name and status', () => {
  const rows = mapRecentImports({ imports: [
    { job_id: 'j2', file_name: 'sales_aug.xlsx', file_type: 'xlsx', status: 'COMPLETED', created_at: '2026-10-06T08:00:00+00:00' },
    { job_id: 'j1', file_name: 'broken.pdf', file_type: 'pdf', status: 'FAILED', created_at: '2026-10-06T07:00:00+00:00' },
    { job_id: 'j0', file_name: 'big.csv', file_type: 'csv', status: 'PROCESSING', created_at: '2026-10-06T06:00:00+00:00' },
  ] });
  assert.deepEqual(rows.map((row) => [row.id, row.name, row.type, row.status]), [
    ['j2', 'sales_aug.xlsx', 'xlsx', 'completed'],
    ['j1', 'broken.pdf', 'pdf', 'failed'],
    ['j0', 'big.csv', 'csv', 'processing'],
  ]);
  assert.equal(rows[0].date, '2026-10-06T08:00:00+00:00');
});

test('no imports yields an empty history (empty state renders)', () => {
  assert.deepEqual(mapRecentImports({ imports: [] }), []);
  assert.deepEqual(mapRecentImports(undefined), []);
});

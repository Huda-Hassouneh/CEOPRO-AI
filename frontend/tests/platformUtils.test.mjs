import test from 'node:test';
import assert from 'node:assert/strict';
import { filterPlatformPage } from '../src/features/platform/platformUtils.js';

const records = [
  { business_name: 'North Shop', country_code: 'JO', primary_currency: 'JOD' },
  { full_name: 'Sam Owner', email: 'sam@example.test' },
];

test('platform page filter searches only display fields and preserves the original page when empty', () => {
  assert.deepEqual(filterPlatformPage(records, ''), records);
  assert.deepEqual(filterPlatformPage(records, ' NORTH '), [records[0]]);
  assert.deepEqual(filterPlatformPage(records, 'SAM@EXAMPLE.TEST'), [records[1]]);
  assert.deepEqual(filterPlatformPage(records, 'JOD'), [records[0]]);
  assert.deepEqual(filterPlatformPage(records, 'missing'), []);
});

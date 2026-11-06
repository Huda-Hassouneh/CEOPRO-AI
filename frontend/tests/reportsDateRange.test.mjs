import test from 'node:test';
import assert from 'node:assert/strict';
import { createReportDateRange } from '../src/features/reports/utils/reportDateRange.js';

test('date-only bounds use UTC calendar midnights', () => {
  assert.deepEqual(createReportDateRange('2026-08-01', '2026-08-20', 'UTC'), {
    startDate: '2026-08-01T00:00:00.000Z',
    endDate: '2026-08-21T00:00:00.000Z',
  });
});

test('date-only bounds use the company timezone in Asia/Amman', () => {
  assert.deepEqual(createReportDateRange('2026-08-01', '2026-08-20', 'Asia/Amman'), {
    startDate: '2026-07-31T21:00:00.000Z',
    endDate: '2026-08-20T21:00:00.000Z',
  });
});

test('DST transition uses consecutive local midnights rather than 24 hours', () => {
  const range = createReportDateRange('2026-03-08', '2026-03-08', 'America/New_York');
  assert.equal(range.startDate, '2026-03-08T05:00:00.000Z');
  assert.equal(range.endDate, '2026-03-09T04:00:00.000Z');
  assert.equal(Date.parse(range.endDate) - Date.parse(range.startDate), 23 * 60 * 60 * 1000);
});

test('single-sided filters preserve the missing side', () => {
  assert.deepEqual(createReportDateRange('2026-08-01', undefined, 'Asia/Amman'), {
    startDate: '2026-07-31T21:00:00.000Z', endDate: undefined,
  });
  assert.deepEqual(createReportDateRange(undefined, '2026-08-20', 'Asia/Amman'), {
    startDate: undefined, endDate: '2026-08-20T21:00:00.000Z',
  });
});

test('invalid and reversed calendar ranges fail closed', () => {
  assert.throws(() => createReportDateRange('2026-02-30', undefined, 'UTC'), RangeError);
  assert.throws(() => createReportDateRange('2026-08-21', '2026-08-20', 'UTC'), RangeError);
  assert.throws(() => createReportDateRange('2026-08-01', undefined, 'Not/AZone'), RangeError);
});

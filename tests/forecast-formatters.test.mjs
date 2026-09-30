import { test } from 'node:test';
import assert from 'node:assert/strict';
import { asForecastDate, forecastFormatters, localize } from '../src/features/forecasting/utils/forecastFormatters.js';
for (const locale of ['en', 'ar']) {
 test(`${locale}: invalid and missing dates never throw`, () => {
   const { formatDate } = forecastFormatters(locale);
   for (const value of [null, undefined, '', 'invalid', '2026-02-30', '2026-02-30T12:00:00Z', '123', new Date(NaN), {}, 0]) assert.equal(formatDate(value), '—');
   for (const value of ['2026-09-30', '2026-09-30T12:00:00Z', new Date('2026-09-30')]) assert.notEqual(formatDate(value), '—');
 });
 test(`${locale}: missing values stay unknown; real zero is preserved`, () => {
   const f = forecastFormatters(locale);
   for (const value of [null, undefined, NaN, Infinity, '', false, ' ']) assert.equal(f.formatNumber(value), '—');
   assert.notEqual(f.formatNumber(0), '—');
   assert.equal(f.formatRange({ lower: null, upper: 4 }), '—');
   assert.equal(f.formatMetric({ value: null, format: 'percent' }, 'units'), '—');
   assert.equal(localize({ en: 'Name', ar: {} }, 'ar'), 'Name');
 });
}
test('date-only boundaries are UTC', () => assert.equal(asForecastDate('2026-09-30').toISOString(), '2026-09-30T00:00:00.000Z'));

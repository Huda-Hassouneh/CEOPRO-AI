import assert from 'node:assert/strict';
import { test } from 'node:test';
import { addDays, forecastWindow, interval, latestForecasts, summarizeForecasts, type ForecastRow } from '../../src/modules/forecasting/service/forecasting.calculations.js';
const start = new Date('2026-09-30T00:00:00Z');
const asOf = new Date('2026-09-30T12:00:00Z');
const row = (offset: number, units: number, changes: Partial<ForecastRow> = {}): ForecastRow => ({
  forecast_id: `f-${offset}`, forecast_target_date: addDays(start, offset), forecast_start_date: null, forecast_end_date: null,
  expected_demand: units, confidence_range_lower: null, confidence_range_upper: null, created_at: new Date('2026-09-29T12:00:00Z'), model_version: 'test', ...changes
});
const week = () => Array.from({ length: 7 }, (_, i) => row(i, i));
test('seven-day window totals and chronological trend preserve zero', () => {
  const s = summarizeForecasts([...week().reverse(), row(-1, 999), row(7, 999)], start, 7, asOf);
  assert.equal(s.expectedDemand, 21); assert.equal(s.trend, 'increasing'); assert.equal(s.coveredDays, 7);
  assert.deepEqual(s.confidenceRange, { lower: null, upper: null });
  assert.equal(summarizeForecasts(week().map(f => ({ ...f, expected_demand: 0 })), start, 7, asOf).expectedDemand, 0);
});
test('latest revision per period wins once; future-created forecasts excluded', () => {
  const rows = [...week(), row(1, 10, { forecast_id: 'revision', created_at: asOf }), row(2, 800, { created_at: addDays(asOf, 1) })];
  assert.equal(summarizeForecasts(rows, start, 7, asOf).expectedDemand, 30);
  assert.equal(latestForecasts(rows, asOf).length, 7);
});
test('empty and incomplete coverage are unavailable, not zero', () => {
  assert.equal(summarizeForecasts([], start, 7, asOf).expectedDemand, null);
  assert.equal(summarizeForecasts([row(0, 0)], start, 7, asOf).status, 'partial');
  assert.equal(summarizeForecasts([row(0, 0)], start, 7, asOf).trend, null);
});
test('period totals are not daily values and cannot be prorated', () => {
  const monthly = row(29, 300, { forecast_start_date: start, forecast_end_date: addDays(start, 29), confidence_range_lower: 250, confidence_range_upper: 350 });
  assert.equal(forecastWindow(monthly)!.start.getTime(), start.getTime());
  assert.equal(summarizeForecasts([monthly], start, 7, asOf).expectedDemand, null);
  const s = summarizeForecasts([monthly], start, 30, asOf);
  assert.equal(s.expectedDemand, 300); assert.deepEqual(s.confidenceRange, { lower: 250, upper: 350 }); assert.equal(s.trend, null);
});
test('overlapping horizons do not double count; marginal bounds are not summed', () => {
  const weekly = row(0, 30, { forecast_start_date: start, forecast_end_date: addDays(start, 6) });
  const s = summarizeForecasts([...week(), weekly], start, 7, asOf);
  assert.equal(s.status, 'overlapping'); assert.equal(s.expectedDemand, null);
  const bounds = week().map(f => ({ ...f, confidence_range_lower: f.expected_demand, confidence_range_upper: f.expected_demand + 1 }));
  assert.deepEqual(summarizeForecasts(bounds, start, 7, asOf).confidenceRange, { lower: null, upper: null });
});
test('invalid bounds and incomplete periods are rejected', () => {
  assert.deepEqual(interval(row(0, 2, { confidence_range_lower: 3, confidence_range_upper: 9 })), { lower: null, upper: null });
  assert.equal(forecastWindow(row(0, 1, { forecast_start_date: start })), null);
  assert.equal(summarizeForecasts([row(0, -1)], start, 7, asOf).status, 'unavailable');
});

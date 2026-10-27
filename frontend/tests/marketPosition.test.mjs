import test from 'node:test';
import assert from 'node:assert/strict';
import { coverageBucket, marketPosition } from '../src/features/pricing/api/marketPosition.js';

test('a competitor comparison wins over an estimate', () => {
  const summary = { headline: { tier: 'EXACT', position_pct: 4, count: 2 }, estimate: { basis: 'PEER_ESTIMATE', market_price: 5 } };
  assert.equal(marketPosition(summary).kind, 'competitors');
  assert.equal(coverageBucket(summary), 'EXACT');
});

test('without a competitor match the market estimate is used, labelled by what it rests on', () => {
  const summary = { headline: null, estimate: { basis: 'MARKET_REFERENCE', market_price: 5, position_pct: 20, count: 3 } };
  assert.deepEqual(marketPosition(summary), { kind: 'estimate', basis: 'MARKET_REFERENCE', pct: 20, marketPrice: 5, count: 3 });
  assert.equal(coverageBucket(summary), 'estimate');
});

test('"none" only when nothing outside the company\'s own cost exists', () => {
  assert.equal(coverageBucket({ headline: null, estimate: { basis: 'INTERNAL_ONLY', market_price: null } }), 'none');
  assert.equal(coverageBucket({ headline: null, estimate: { basis: 'SOMETHING_NEW', market_price: 5 } }), 'none');
  assert.equal(coverageBucket(undefined), 'none');
});

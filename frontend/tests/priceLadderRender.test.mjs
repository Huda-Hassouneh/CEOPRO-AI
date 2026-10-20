// Renders the price ladder's added-value guidance and the report page (server-side, no browser).
import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { createServer } from 'vite';

let vite;
test.before(async () => { vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' }); });
test.after(async () => { await vite.close(); });

async function render(build) {
  const { I18nProvider } = await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
  const client = new QueryClient();
  const tree = await build();
  return renderToStaticMarkup(
    React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, null, React.createElement(I18nProvider, null, tree))),
  );
}

const tier = (count, extra = {}) => ({ count, items: [], low: null, median: null, high: null, your_position_pct: null, direction: null, ...extra });
const ladder = (guidance, over = {}) => ({
  product_id: 'p1', currency: 'JOD', your_price: 4.2, category: 'burgers', covered: true,
  headline: { tier: 'ADDED_VALUE', count: 1, median_comparable: 3, position_pct: 40, direction: 'own_richer' },
  tiers: { EXACT: tier(0), EQUIVALENT: tier(0), SIMILAR: tier(0), ADDED_VALUE: tier(1, { items: [], low: 3, median: 3, high: 3 }) },
  premium_band: { band_pct: 60, source: 'default', samples: 2 }, added_value_guidance: guidance, ...over,
});
const guidance = (over = {}) => ({ kind: 'range_not_a_price', base_price: 3, base_items: 1, range_low: 3.06, range_high: 4.8, band_pct: 60,
  band_source: 'default', band_samples: 2, your_price: 4.2, position: 'within_range', your_premium_pct: 40, ...over });

async function ladderHtml(data, props = {}) {
  return render(async () => {
    const { PriceLadder } = await vite.ssrLoadModule('/src/features/pricing/components/PriceLadder.jsx');
    return React.createElement(PriceLadder, { ladder: data, ...props });
  });
}

test('guidance says it is a range, not a price, and where your price sits', async () => {
  const html = await ladderHtml(ladder(guidance()));
  assert.match(html, /data-testid="added-value-guidance"/);
  assert.match(html, /This is a range, not a recommended price/);
  assert.match(html, /Your price is inside that range/);
  assert.match(html, /Default band/);
});

test('each band source is named, and the editor appears only when the screen can save', async () => {
  assert.match(await ladderHtml(ladder(guidance({ band_source: 'observed', band_samples: 9 }))), /Band taken from 9 comparisons/);
  const owner = await ladderHtml(ladder(guidance({ band_source: 'owner' })), { onSetBand: () => {} });
  assert.match(owner, /Band set by you/);
  assert.match(owner, /Use the market band/); // only an owner-set band can be cleared
  assert.match(owner, /Set your band/);
  const readOnly = await ladderHtml(ladder(guidance()));
  assert.doesNotMatch(readOnly, /Set your band/);
  assert.doesNotMatch(await ladderHtml(ladder(guidance()), { onSetBand: () => {} }), /Use the market band/);
});

test('no guidance block when the product has like-for-like evidence', async () => {
  assert.doesNotMatch(await ladderHtml(ladder(null)), /added-value-guidance/);
});

const row = (over = {}) => ({
  product_id: 'p1', name: 'Double extra cheese burger', currency: 'JOD', your_price: 4.2,
  headline: { tier: 'ADDED_VALUE', count: 1, median_comparable: 3, position_pct: 40 },
  tiers: { EXACT: tier(0), EQUIVALENT: tier(0), SIMILAR: tier(0), ADDED_VALUE: tier(1) },
  added_value_guidance: guidance(), ...over,
});

async function reportHtml(query) {
  return render(async () => {
    const { PriceComparisonReportView } = await vite.ssrLoadModule('/src/features/pricing/pages/PriceComparisonReportPage.jsx');
    return React.createElement(PriceComparisonReportView, { query });
  });
}

test('the report shows its rows with the justified range, and no position for added-value rows', async () => {
  const html = await reportHtml({ isPending: false, isError: false, data: { products: [
    row(),
    row({ product_id: 'p2', name: 'Cheese burger', your_price: 3.5, headline: { tier: 'EXACT', count: 1, position_pct: 16.7 }, tiers: { EXACT: tier(1), EQUIVALENT: tier(0), SIMILAR: tier(0), ADDED_VALUE: tier(0) }, added_value_guidance: null }),
  ] } });
  assert.match(html, /<caption[^>]*>Price comparison report/); // a table is announced by its caption
  assert.match(html, /<th scope="row" dir="auto"[^>]*>Double extra cheese burger/);
  assert.match(html, /JOD\s?3\.06 – JOD\s?4\.80|JOD\s?3\.06/);
  assert.match(html, /Your price is inside that range/);
  assert.match(html, /17% above|16\.7% above|17 % above/);
});

test('the report says so when it is loading, empty or failed, and offers Retry on failure', async () => {
  assert.doesNotMatch(await reportHtml({ isPending: true }), /<table/);
  assert.match(await reportHtml({ isPending: false, isError: false, data: { products: [] } }), /No product has competitor evidence yet/);
  const failed = await reportHtml({ isPending: false, isError: true, refetch: () => {} });
  assert.match(failed, /The report could not be loaded/);
  assert.match(failed, />Retry</);
});

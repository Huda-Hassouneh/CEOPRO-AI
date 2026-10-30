import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createServer } from 'vite';

test('market structure distinguishes legacy/manual records from website collection', async () => {
  const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  try {
    const { MarketStructure } = await vite.ssrLoadModule('/src/features/market-intelligence/components/MarketStructure.jsx');
    const { I18nProvider } = await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
    const client = new QueryClient();
    client.setQueryData(['market-structure'], {
      businesses: 2, by_relationship: {}, chains: 0, top_categories: [], distance_bands: {},
      websites: { known: 2, read: 1, with_prices: 1 },
      product_prices: [{ product: 'Oil', currency: 'JOD', your_price: 9.5, min: 9, max: 10, median: 9.5, count: 2, position: 'within', prices: [
        { competitor: 'Manual rival', price: 9, source_url: 'https://manual.example', provenance: 'manual' },
        { competitor: 'Website rival', price: 10, source_url: 'https://website.example', provenance: 'scraped' },
      ] }],
    });
    const html = renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
      React.createElement(I18nProvider, null, React.createElement(MarketStructure))));
    assert.match(html, /Manual observation/);
    assert.match(html, /Website collection/);
    assert.match(html, /not independently verified/);
    assert.doesNotMatch(html, /found by your scans|against published competitor prices/);
  } finally {
    await vite.close();
  }
});

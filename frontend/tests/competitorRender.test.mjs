// Renders the competitor data screens (server-side, no browser) to check what the owner actually reads.
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

async function render(element) {
  const { I18nProvider } = await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
  const client = new QueryClient();
  const tree = await element({ React, client });
  return renderToStaticMarkup(
    React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, null, React.createElement(I18nProvider, null, tree))),
  );
}

const blocked = {
  score: 14, needs_setup: ['COMMENTS'],
  facets: {
    PROFILE: { status: 'SUCCEEDED', items_found: 2, can_retry: true, next_step: 'none' },
    NEWS: { status: 'FAILED', reason_code: 'NO_NEWS', reason_detail: 'No recent news found.', can_retry: true, next_step: 'retry' },
    COMMENTS: { status: 'BLOCKED', reason_code: 'NO_CREDENTIALS', reason_detail: 'YOUTUBE_API_KEY is not set for the service that collects comments.', can_retry: true, next_step: 'admin' },
  },
};

test('the completeness panel shows each reason and detail as text, who must act, and Retry only where it helps', async () => {
  const html = await render(async ({ React }) => {
    const { DataCompleteness } = await vite.ssrLoadModule('/src/features/market-intelligence/components/DataCompleteness.jsx');
    return React.createElement(DataCompleteness, { completeness: blocked, competitorId: 'c1' });
  });
  assert.doesNotMatch(html, /YOUTUBE_API_KEY/); // owners are never shown a variable name
  assert.match(html, /Ask the service operator to enable this/);
  assert.match(html, /Copy request for the operator/);
  assert.match(html, /Waiting on your administrator to finish the service setup: Video comments/);
  assert.match(html, /Retry this/); // NEWS can be retried on its own
  assert.equal((html.match(/Retry this/g) || []).length, 1); // ...but COMMENTS, which needs the administrator, has no button
});

test('the list row explains what is missing without opening the profile', async () => {
  const html = await render(async ({ React }) => {
    const { CompetitorDataChips } = await vite.ssrLoadModule('/src/features/market-intelligence/components/DataCompleteness.jsx');
    return React.createElement(CompetitorDataChips, { data: { comments_collected: 0, data_completeness: blocked }, competitorId: 'c1' });
  });
  assert.match(html, /Why is something missing\? \(2\)/);
  assert.doesNotMatch(html, /YOUTUBE_API_KEY/);
});

test('an empty comments panel gives the live reason instead of a stale hint', async () => {
  const html = await render(async ({ React, client }) => {
    client.setQueryData(['competitor-data-status', 'c1'], { competitor_id: 'c1', queued: false, ...blocked });
    client.setQueryData(['competitor-comments', 'c1', 'helpful', null, null, null, null], { pages: [{ summary: { comments: 0, replies: 0, people_agreeing: 0, held_back_for_safety: 0, sentiment: { positive: 0, negative: 0, neutral: 0, not_analysed: 0 } }, comments: [], next_offset: null }], pageParams: [0] });
    const { CompetitorComments } = await vite.ssrLoadModule('/src/features/market-intelligence/components/CompetitorComments.jsx');
    return React.createElement(CompetitorComments, { competitorId: 'c1' });
  });
  assert.doesNotMatch(html, /YOUTUBE_API_KEY/);
  assert.match(html, /Ask the service operator to enable this/);
  assert.doesNotMatch(html, /Collect comments now/); // retrying cannot help here
});

test('comments show sentiment counts, opportunity markers and a link to the original', async () => {
  const html = await render(async ({ React, client }) => {
    const comment = { id: 'r1', author: 'Sam', text: 'Cold food', sentiment: 'negative', signal: 'opportunity', people_agreeing: 9, action_status: 'noted', url: 'https://www.youtube.com/watch?v=v&lc=c', replies: [], reply_count: 0, platform: 'YouTube', date: null, rating: null };
    client.setQueryData(['competitor-comments', 'c1', 'helpful', null, null, null, null], { pages: [{ summary: { comments: 1, replies: 0, people_agreeing: 9, held_back_for_safety: 0, sentiment: { positive: 0, negative: 1, neutral: 0, not_analysed: 2 }, platforms: { YouTube: 3, 'Google Places': 2 }, last_collected_at: '2026-10-18T10:00:00Z', themes: [{ theme: 'waiting', mentions: 4, negative: 3, positive: 0, example: { id: 'r1', text: 'Cold food', people_agreeing: 9 } }] }, comments: [comment], next_offset: null }], pageParams: [0] });
    const { CompetitorComments } = await vite.ssrLoadModule('/src/features/market-intelligence/components/CompetitorComments.jsx');
    return React.createElement(CompetitorComments, { competitorId: 'c1' });
  });
  assert.match(html, /Negative · 1/);
  assert.match(html, /Opportunity/);
  assert.match(html, /href="https:\/\/www\.youtube\.com\/watch\?v=v&amp;lc=c"/);
  assert.match(html, /2 not analysed yet/);
  assert.match(html, /Waiting time · 4/);          // a theme, with how many mentions
  assert.match(html, /3 negative/);
  assert.match(html, /To review/);                  // filter for comments nobody handled yet
  assert.match(html, /YouTube · 3/);                // two sources, so platform chips appear
  assert.match(html, /collected Oct 18, 2026/);
  assert.match(html, /aria-pressed="true"[^>]*>[^<]*<svg[^>]*>.*?Noted/s); // the comment is marked as noted
});

test('a stored link that is not a web link is never opened from a comment', async () => {
  const html = await render(async ({ React, client }) => {
    const comment = { id: 'r1', author: 'Sam', text: 'Cold food and slow', sentiment: 'neutral', signal: null, people_agreeing: 0, url: 'javascript:alert(1)', replies: [], reply_count: 0, platform: 'YouTube', date: null, rating: null };
    client.setQueryData(['competitor-comments', 'c1', 'helpful', null, null, null, null], { pages: [{ summary: { comments: 1, replies: 0, people_agreeing: 0, held_back_for_safety: 0, platforms: { YouTube: 1 }, themes: [], sentiment: { positive: 0, negative: 0, neutral: 1, not_analysed: 0 } }, comments: [comment], next_offset: null }], pageParams: [0] });
    const { CompetitorComments } = await vite.ssrLoadModule('/src/features/market-intelligence/components/CompetitorComments.jsx');
    return React.createElement(CompetitorComments, { competitorId: 'c1' });
  });
  assert.match(html, /Cold food and slow/);
  assert.doesNotMatch(html, /javascript:/);
});

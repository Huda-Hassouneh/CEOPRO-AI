import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright-core';

const api = process.env.API_URL;
const base = process.env.APP_URL;
const locale = process.env.E2E_LOCALE || 'en';
const translations = JSON.parse(await readFile(new URL(`../../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
const ui = translations.connectData;
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH });

const csv = (product, quantity = '2') => Buffer.from(
  `product_name,quantity,unit_price,currency,transaction_date\n${product},${quantity},6.25,JOD,2026-10-20\n`,
);
const waitForResponseCount = async (responses, expected) => {
  const deadline = Date.now() + 30000;
  while (responses.length < expected && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
  assert.equal(responses.length, expected, `expected ${expected} upload response(s)`);
};

try {
  const page = await browser.newPage({ viewport: { width: locale === 'ar' ? 390 : 1365, height: 900 } });
  await page.addInitScript((language) => localStorage.setItem('ceopro_locale', language), locale);
  await page.goto(`${base}/login`);
  await page.locator('input[type="email"]').fill(process.env.E2E_EMAIL);
  await page.locator('input[type="password"]').fill(process.env.E2E_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30000 });
  const historicalDashboard = page.waitForResponse((response) =>
    response.url().includes('/dashboard/command-center') && response.status() === 200);
  await page.goto(`${base}/dashboard`);
  const historical = await (await historicalDashboard).json();
  assert.equal(historical.has_sales, true, 'older canonical sales must prevent first-time setup');
  if (locale === 'en') {
    assert.equal(historical.metrics.revenue.amount, 0, 'older sales must not enter the current period');
    assert.equal(historical.sales_trend.has_data, false);
    await page.getByText(translations.commandCenter.trend.empty).first().waitFor();
    assert.equal(await page.locator('.apex-grid--main-side .apex-chart').count(), 0, 'quiet period must show the empty chart state');
  } else {
    assert.equal(historical.metrics.revenue.amount, 37.5, 'Arabic pass sees the completed English imports');
  }
  await page.goto(`${base}/connect-data`);
  await page.getByRole('heading', { name: ui.page.title }).waitFor();
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');

  const postResponses = [];
  page.on('response', (response) => {
    if (response.url().includes('/extraction/upload') && response.request().method() === 'POST') {
      postResponses.push(response);
    }
  });

  const validMarker = locale === 'ar' ? process.env.E2E_ARABIC_MARKER : process.env.E2E_VALID_MARKER;
  const validFile = { name: `${validMarker}.csv`, mimeType: 'text/csv', buffer: csv(validMarker) };
  // The Data Connections page also contains a reviews import input; select
  // the accessible business-data upload control, not whichever file input
  // happens to appear first in the DOM.
  const input = page.getByLabel(translations.dataIngestion.browse);
  await input.setInputFiles(validFile);
  await page.getByRole('button', { name: ui.actions.prepareImport }).click();
  await waitForResponseCount(postResponses, 1);
  await page.locator('.connect-data-toast .ceopro-toast').waitFor();
  assert.equal(postResponses.length, 1, 'upload must use the real extraction HTTP endpoint');
  const first = await postResponses[0].json();
  assert.equal(postResponses[0].status(), 200);
  assert.equal(first.promotion.rows_promoted, 1, 'valid sales row should use existing canonical promotion');
  assert.equal(first.promotion.products_created, 0, 'exact tenant product identity should be reused');

  const token = await page.evaluate(() => JSON.parse(localStorage.getItem('ceopro_auth_session')).accessToken);
  const detailResponse = await page.request.get(`${api}/extraction/import-drafts/${first.import_draft.batch_id}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  assert.equal(detailResponse.status(), 200);
  const detail = await detailResponse.json();
  assert.equal(detail.category, 'sales');
  assert.equal(detail.rows.length, 1);
  assert.equal(detail.rows[0].canonical_posting_status, 'committed');

  const historyResponse = await page.request.get(`${api}/extraction/imports`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  assert.equal(historyResponse.status(), 200);
  const history = await historyResponse.json();
  assert.ok(history.imports.some((item) => item.file_name === validFile.name));

  await page.getByRole('button', { name: ui.drafts.open }).first().click();
  const preview = page.locator('.import-draft-detail');
  await preview.getByText(validMarker).waitFor();
  await preview.getByRole('region', { name: ui.drafts.rowsLabel })
    .getByText(ui.drafts.states.committed).first().waitFor();
  if (locale === 'en') {
    await preview.getByRole('button', { name: ui.drafts.approveBatch }).click();
    await page.locator('#import-review-reason').fill('Owner reviewed imported sales evidence');
    const reviewResponse = page.waitForResponse((response) =>
      response.url().includes(`/extraction/import-drafts/${first.import_draft.batch_id}/reviews`)
      && response.request().method() === 'POST');
    await page.getByRole('button', { name: ui.drafts.confirmAction }).click();
    assert.equal((await reviewResponse).status(), 200, 'owner review must be confirmed by the backend');
    await preview.locator('.import-draft-history').getByText(ui.drafts.review.approved).waitFor();
    const reviewHistoryResponse = await page.request.get(`${api}/extraction/import-drafts/${first.import_draft.batch_id}/reviews`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    assert.equal(reviewHistoryResponse.status(), 200);
    assert.equal((await reviewHistoryResponse.json()).reviews[0].decision, 'approve');
  }
  await page.getByRole('button', { name: ui.drafts.closePreview }).click();

  // An identical file replay remains a separately reviewable request but the
  // established content identity prevents a second canonical sale.
  const replay = await page.request.post(`${api}/extraction/upload`, {
    headers: { Authorization: `Bearer ${token}` },
    multipart: { file: { name: 'same-sales-replay.csv', mimeType: 'text/csv', buffer: validFile.buffer } },
  });
  assert.equal(replay.status(), 200);
  assert.equal((await replay.json()).promotion.rows_duplicate, 1);

  const otherTenant = await page.request.get(`${api}/extraction/import-drafts/${first.import_draft.batch_id}`, {
    headers: { Authorization: `Bearer ${process.env.E2E_OTHER_TENANT_TOKEN}` },
  });
  assert.equal(otherTenant.status(), 404, 'other tenant must not inspect the import draft');

  if (locale === 'en') {
    const secondName = process.env.E2E_RETRY_MARKER;
    const empty = { name: 'empty-file.csv', mimeType: 'text/csv', buffer: Buffer.alloc(0) };
    const mixedStart = postResponses.length;
    await input.setInputFiles([
      { name: `${secondName}.csv`, mimeType: 'text/csv', buffer: csv(secondName) },
      empty,
    ]);
    await page.getByRole('button', { name: ui.actions.prepareImport }).click();
    await waitForResponseCount(postResponses, mixedStart + 2);
    await page.locator('.connect-data-toast .ceopro-toast').waitFor();
    assert.equal(postResponses[mixedStart].status(), 200);
    assert.equal(postResponses[mixedStart + 1].status(), 400, 'empty uploads should receive a client-safe validation error');
    const retrySelection = page.locator('.ceopro-upload-list');
    await retrySelection.getByText('empty-file.csv').waitFor();
    assert.equal(await retrySelection.getByText(`${secondName}.csv`).count(), 0, 'completed files should be removed from retry selection');

    const removeLabel = translations.dataIngestion.removeFile.replace('{{name}}', 'empty-file.csv');
    await page.getByRole('button', { name: removeLabel }).click();
    const corrected = { name: 'empty-file.csv', mimeType: 'text/csv', buffer: csv(process.env.E2E_CORRECTED_MARKER) };
    await input.setInputFiles(corrected);
    await page.getByRole('button', { name: ui.actions.prepareImport }).click();
    await waitForResponseCount(postResponses, mixedStart + 3);
    await page.locator('.connect-data-toast .ceopro-toast').waitFor();
    assert.equal(postResponses[mixedStart + 2].status(), 200, 'the retained failure can be corrected and submitted again');
    console.log('PASS upload retry: completed file cleared; rejected file retained, corrected, and accepted.');
  } else {
    const invalidName = process.env.E2E_INVALID_MARKER;
    await input.setInputFiles({ name: `${invalidName}.csv`, mimeType: 'text/csv', buffer: csv(invalidName, '-2') });
    const beforeInvalid = postResponses.length;
    await page.getByRole('button', { name: ui.actions.prepareImport }).click();
    await waitForResponseCount(postResponses, beforeInvalid + 1);
    await page.locator('.connect-data-toast .ceopro-toast').waitFor();
    assert.equal(postResponses.at(-1).status(), 200, 'row-level validation failure is retained as a draft, not a transport failure');
    const invalidResult = await postResponses.at(-1).json();
    assert.equal(invalidResult.rows_partial, 1);
    assert.equal(invalidResult.promotion.rows_promoted, 0);
    const invalidDetailResponse = await page.request.get(`${api}/extraction/import-drafts/${invalidResult.import_draft.batch_id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    assert.equal(invalidDetailResponse.status(), 200);
    const invalidDetail = await invalidDetailResponse.json();
    assert.equal(invalidDetail.rows[0].canonical_posting_status, 'not_committed');
    assert.ok(invalidDetail.rows[0].validation_findings.length > 0);
    const draftListResponse = await page.request.get(`${api}/extraction/import-drafts?limit=10&offset=0`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    assert.equal(draftListResponse.status(), 200);
    const draftIndex = (await draftListResponse.json()).items.findIndex((item) =>
      item.batch_id === invalidResult.import_draft.batch_id);
    assert.ok(draftIndex >= 0, 'invalid draft must remain in import history');
    await page.reload();
    await page.locator('.import-drafts-list-table tbody tr').nth(draftIndex)
      .getByRole('button', { name: ui.drafts.open }).click();
    const invalidPreview = page.locator('.import-draft-detail');
    await invalidPreview.getByText(invalidName).waitFor();
    await invalidPreview.getByRole('region', { name: ui.drafts.rowsLabel })
      .getByText(ui.drafts.states.not_committed).first().waitFor();
  }

  const dashboardResponse = page.waitForResponse((response) =>
    response.url().includes('/dashboard/command-center') && response.status() === 200);
  await page.goto(`${base}/dashboard`);
  const dashboard = await (await dashboardResponse).json();
  const expectedRevenue = locale === 'en' ? 37.5 : 50;
  const expectedUnits = locale === 'en' ? 6 : 8;
  assert.equal(dashboard.metrics.revenue.amount, expectedRevenue, 'canonical invoice totals must count once');
  assert.equal(dashboard.metrics.units_sold.units, expectedUnits);
  assert.equal(dashboard.today.orders, 0, 'the imports are dated two days ago');
  assert.equal(dashboard.has_sales, true);
  assert.equal(dashboard.sales_trend.has_data, true);
  assert.equal(dashboard.sales_trend.points.find((point) => point.date === '2026-10-20')?.value,
    expectedRevenue, 'chart values must match canonical period revenue');
  assert.ok(dashboard.top_products.some((product) => product.name === validMarker && product.revenue === 12.5));
  await page.locator('.apex-chart').waitFor();
  const expectedDisplay = new Intl.NumberFormat(locale, { style: 'currency', currency: 'JOD', maximumFractionDigits: 0 }).format(expectedRevenue);
  await page.waitForFunction((value) => document.querySelector('.apex-grid--stats .apex-stat__value')?.textContent?.includes(value), expectedDisplay);
  assert.equal(await page.locator('html').getAttribute('dir'), locale === 'ar' ? 'rtl' : 'ltr');

  const periodResponse = page.waitForResponse((response) =>
    response.url().includes('/dashboard/command-center?window_days=7') && response.status() === 200);
  await page.getByRole('button', { name: translations.commandCenter.window.days.replace('{{count}}', '7') }).click();
  assert.equal((await (await periodResponse).json()).metrics.revenue.amount, expectedRevenue);
  const ninetyResponse = page.waitForResponse((response) =>
    response.url().includes('/dashboard/command-center?window_days=90') && response.status() === 200);
  await page.getByRole('button', { name: translations.commandCenter.window.days.replace('{{count}}', '90') }).click();
  const ninety = await (await ninetyResponse).json();
  assert.equal(ninety.metrics.revenue.amount, expectedRevenue);
  assert.equal(ninety.metrics.revenue.change_pct, null, 'insufficient prior-window history must not fabricate growth');

  if (locale === 'en') {
    const failedEndpoint = '**/dashboard/command-center**';
    await page.route(failedEndpoint, (route) => route.abort());
    await page.reload();
    await page.getByText(translations.commandCenter.error.title).waitFor({ timeout: 30000 });
    await page.unroute(failedEndpoint);
    await page.getByRole('button', { name: translations.demandApex.actions.retry }).click();
    await page.locator('.apex-grid--main-side .apex-chart').waitFor();
  }

  console.log(`PASS authenticated Data Connections import flow (${locale}, ${locale === 'ar' ? 'mobile RTL' : 'desktop'}): upload, history, preview, tenant isolation, canonical status.`);
} finally {
  await browser.close();
}

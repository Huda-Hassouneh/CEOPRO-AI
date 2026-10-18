import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { I18nProvider } from '../src/app/providers/I18nProvider.jsx';
import { translate } from '../src/shared/lib/i18n.js';
import Table from '../src/shared/components/ui/Table.jsx';
import PasswordInput from '../src/shared/components/ui/PasswordInput.jsx';
import Stepper from '../src/shared/components/ui/Stepper.jsx';
import Tabs from '../src/shared/components/ui/Tabs.jsx';
import { ShopifyAuthorizationFields, storeErrorMessage } from '../src/features/data-connections/components/WebsiteStoreSetup.jsx';
import { AlertEvent } from '../src/features/smart-alerts/SmartAlertsPage.jsx';

const h = React.createElement;
const noop = () => {};
for (const locale of ['en', 'ar']) {
  test(`${locale}: shared controls resolve their translated accessibility and empty-state defaults`, () => {
    const previous = globalThis.window;
    try {
      globalThis.window = { localStorage: { getItem: () => locale } };
      const html = renderToStaticMarkup(h(I18nProvider, null, h(React.Fragment, null,
        h(Table, { columns: [{ header: translate(locale, 'catalog.fields.name'), accessor: 'name' }], data: [] }),
        h(PasswordInput, { label: translate(locale, 'interfaceCopy.password') }),
        h(Stepper, { steps: [] }), h(Tabs, { tabs: [] }),
      )));
      for (const key of ['interfaceCopy.noDataAvailable', 'auth.common.showPassword', 'interfaceCopy.progress', 'interfaceCopy.tabs']) {
        assert.ok(html.includes(translate(locale, key)), key);
      }
      assert.doesNotMatch(html, /interfaceCopy\.|auth\.common\./);
      if (locale === 'ar') assert.ok(!html.includes('No data available'));
    } finally {
      if (previous === undefined) delete globalThis.window; else globalThis.window = previous;
    }
  });
  test(`${locale}: Shopify labels and unknown store errors never expose translation keys`, () => {
    const t = (key, values) => translate(locale, key, values);
    const html = renderToStaticMarkup(h(ShopifyAuthorizationFields, { t, url: '', setUrl: noop, minutes: '60', setMinutes: noop,
      consent: false, setConsent: noop, includeTests: false, setIncludeTests: noop, busy: false }));
    for (const key of ['storeConnection.shopify.domain', 'storeConnection.shopify.includeTests', 'storeConnection.every60']) {
      assert.ok(html.includes(t(key)), key);
    }
    assert.doesNotMatch(html, /storeConnection\./);
    const unknown = storeErrorMessage({ code: 'STORE_UNKNOWN_FUTURE_ERROR' }, t);
    assert.equal(unknown, t('storeConnection.errors.STORE_SERVICE_UNAVAILABLE'));
  });
  test(`${locale}: Smart Alerts retains actions and localized status labels`, () => {
    const t = (key, values) => translate(locale, key, values);
    const html = renderToStaticMarkup(h(AlertEvent, { t, locale, canManage: true,
      action: { isPending: false, mutate: noop }, event: { alert_event_id: 'test', observed_value: -8,
        created_at: '2026-10-17T12:00:00Z', trigger_facts: { name: '<script>example</script>' } } }));
    for (const key of ['smartAlerts.states.open', 'smartAlerts.acknowledge', 'smartAlerts.resolve']) assert.ok(html.includes(t(key)), key);
    assert.ok(!html.includes('<script>'));
    assert.doesNotMatch(html, /smartAlerts\./);
  });
}

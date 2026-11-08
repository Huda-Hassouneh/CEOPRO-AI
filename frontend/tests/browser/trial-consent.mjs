// Offline browser acceptance: route every request; no listening API or providers.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright-core';

const operation = '11111111-1111-4111-8111-111111111111';
const origin = 'http://127.0.0.1:19473';
const chrome = process.env.CHROMIUM_PATH || [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
].find(existsSync);
assert.ok(chrome, 'Installed Chromium required');
const fixture = `
    import React, { useState } from 'react';
    import { createRoot } from 'react-dom/client';
    import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
    import { I18nProvider } from './src/app/providers/I18nProvider.jsx';
    import { loadLocale } from './src/shared/lib/i18n.js';
    import { useAuthStore } from './src/features/auth/store/authStore.js';
    import httpClient, { configureHttpClientAuth } from './src/shared/lib/httpClient.js';
    import { TrialConsentPanel } from './src/features/billing/components/TrialConsentPanel.jsx';
    httpClient.defaults.baseURL = location.origin;
    configureHttpClientAuth({ getAccessToken: () => 'synthetic-offline-token' });
    useAuthStore.setState({ tenantId: 'tenant-original', user: { id: 'actor-original' } });
    const client = new QueryClient();
    window.refreshPreview = () => client.invalidateQueries({ queryKey: ['trialConsent'] });
    window.switchIdentity = () => useAuthStore.setState({ tenantId: 'tenant-other', user: { id: 'actor-other' } });
    function Fixture() {
      const [props, setProps] = useState({ operationId: '${operation}' });
      window.showPreview = value => setProps(value);
      return <TrialConsentPanel {...props} />;
    }
    loadLocale(localStorage.getItem('ceopro_locale') || 'en').then(() => {
      createRoot(document.getElementById('root')).render(
        <QueryClientProvider client={client}><I18nProvider><Fixture /></I18nProvider></QueryClientProvider>
      );
      window.fixtureReady = true;
    });`;
const input = resolve('.trial-preview-offline.jsx');
const bundled = await build({
  configFile: false, envDir: false, logLevel: 'silent',
  define: { 'import.meta.env.VITE_RECURRING_JOURNEY_PREVIEW_ENABLED': JSON.stringify('false'),
    'import.meta.env.VITE_RECURRING_CONSENT_ENABLED': JSON.stringify('false'),
    'process.env.NODE_ENV': JSON.stringify('production') },
  plugins: [react(), { name: 'offline-fixture',
    resolveId(id) { if (id === input) return input; },
    load(id) { if (id === input) return fixture; },
  }],
  build: { write: false, minify: false, lib: { entry: input, formats: ['es'] },
    rollupOptions: { output: { codeSplitting: false } } },
});
const outputs = Array.isArray(bundled) ? bundled : [bundled];
const script = outputs.flatMap(result => result.output).find(item => item.type === 'chunk').code;
const browser = await chromium.launch({ executablePath: chrome, headless: true });
const checks=[];
try {
  for (const locale of ['en','ar']) {
    const messages=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing.trialConsent;
    const context=await browser.newContext();const page=await context.newPage();const calls=[],errors=[],unexpected=[];
    let approved=false;
    page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(value=>localStorage.setItem('ceopro_locale',value),locale);
    await page.route('**/*',async route=>{
      const req=route.request(), url=new URL(req.url());
      if (url.href===origin+'/') return route.fulfill({contentType:'text/html',body:'<div id="root"></div><script type="module" src="/fixture.js"></script>'});
      if (url.href===origin+'/fixture.js') return route.fulfill({contentType:'text/javascript',body:script});
      const prefix=origin+'/billing/trial-journeys/'+operation+'/consent/';
      if (url.href.startsWith(prefix)) {
        calls.push({method:req.method(),path:url.pathname,body:req.postDataJSON()});
        const action=url.pathname.split('/').at(-1);let data;
        if (action==='preparation') data={operation_id:operation,state:approved?'prepared':'pending_policy',
          policy_revision:approved?'synthetic-v1':null,agreement_text:approved?'SYNTHETIC TEST AGREEMENT - NOT LEGAL':null,
          missing_approvals:approved?[]:['agreement_text','trial_start_rule','operator_details'],
          commercial_terms:{renewal_amount:'59.000000000000001',currency:'USD',interval_months:1,trial_duration_days:14}};
        else if (action==='present') data={state:'presented',presentation_id:operation,challenge:'x'.repeat(72),policy_revision:'synthetic-v1'};
        else if (action==='accept') data={state:'accepted',accepted_at:'synthetic-db-clock'};
        else if (action==='withdraw') data={state:'withdrawn',recorded_at:'synthetic-db-clock'};
        else throw new Error('Unexpected action');
        return route.fulfill({contentType:'application/json',body:JSON.stringify(data)});
      }
      unexpected.push(req.url());return route.abort();
    });
    await page.goto(origin);await page.waitForFunction(()=>window.fixtureReady);
    assert.equal(await page.locator('section').count(),0);assert.equal(calls.length,0);
    checks.push(locale+': default-off, no requests');
    await page.evaluate(op=>window.showPreview({operationId:op,enabled:true}),operation);
    await page.getByText('59.000000000000001 USD',{exact:true}).waitFor();
    const checkbox=page.getByRole('checkbox');
    assert.equal(await checkbox.isChecked(),false);assert.equal(await checkbox.isEnabled(),false);
    assert.equal(await page.getByRole('button',{name:messages.accept,exact:true}).isEnabled(),false);
    assert.equal(await page.locator('li').count(),3);
    assert.equal(await page.locator('section').getAttribute('dir'),locale==='ar'?'rtl':'ltr');
    assert.ok(calls.every(call=>call.method==='GET'));checks.push(locale+': missing policies, frozen decimal, unchecked/disabled, RTL');
    approved=true;await page.evaluate(()=>window.refreshPreview());
    await page.getByRole('button',{name:messages.present,exact:true}).click();
    await checkbox.waitFor();await page.waitForFunction(()=>!document.querySelector('input[type="checkbox"]').disabled);
    assert.equal(await checkbox.isChecked(),false);
    assert.equal(await page.getByRole('button',{name:messages.accept,exact:true}).isEnabled(),false);
    await checkbox.check();await page.getByRole('button',{name:messages.accept,exact:true}).click();
    await page.getByText(messages.recorded,{exact:true}).waitFor();
    assert.deepEqual(calls.find(call=>call.path.endsWith('/accept')).body,{language:locale,presentation_id:operation,challenge:'x'.repeat(72),checked:true});
    checks.push(locale+': synthetic approved boundary requires fresh explicit checkbox and sends no terms/actor');
    await page.getByRole('button',{name:messages.withdraw,exact:true}).click();
    await page.getByText(messages.withdrawn,{exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:messages.accept,exact:true}).isEnabled(),false);
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    assert.ok(calls.every(call=>call.path.includes('/consent/')));
    checks.push(locale+': withdrawal remains distinct, no dispatch/activation/provider requests');
    await context.close();
  }
  console.log(JSON.stringify({status:'PASS',checks},null,2));
} finally {await browser.close();}

// Fully intercepted SDK and API; never provider acceptance or a payment.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright-core';
const origin='https://merchant.example.test',op='11111111-1111-4111-8111-111111111111',txn='txn_'+'a'.repeat(26);
const chrome=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
assert.ok(chrome);
const fixture=`
import React from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {I18nProvider} from './src/app/providers/I18nProvider.jsx';import {loadLocale} from './src/shared/lib/i18n.js';
import {useAuthStore} from './src/features/auth/store/authStore.js';
import httpClient,{configureHttpClientAuth} from './src/shared/lib/httpClient.js';
import {PaddlePaymentPage} from './src/features/billing/pages/PaddlePaymentPage.jsx';
httpClient.defaults.baseURL=location.origin;configureHttpClientAuth({getAccessToken:()=> 'synthetic-offline-token'});
useAuthStore.setState({tenantId:'tenant-original',user:{id:'actor-original'}});
window.switchIdentity=()=>useAuthStore.setState({tenantId:'other-tenant',user:{id:'other-actor'}});
loadLocale(localStorage.getItem('ceopro_locale')||'en').then(()=>createRoot(document.getElementById('root')).render(
<QueryClientProvider client={new QueryClient()}><I18nProvider><MemoryRouter initialEntries={[location.pathname+location.search]}><PaddlePaymentPage /></MemoryRouter></I18nProvider></QueryClientProvider>));`;
const input=resolve('.paddle-payment-offline.jsx');
const result=await build({configFile:false,envDir:false,logLevel:'silent',define:{
  'import.meta.env.VITE_RECURRING_JOURNEY_ENABLED':JSON.stringify('true'),
  'import.meta.env.VITE_PADDLE_CHECKOUT_ENABLED':JSON.stringify('true'),
  'import.meta.env.VITE_PADDLE_CLIENT_TOKEN':JSON.stringify('test_synthetic'),
  'import.meta.env.VITE_PADDLE_CHECKOUT_ORIGIN':JSON.stringify(origin),
  'import.meta.env':JSON.stringify({VITE_RECURRING_JOURNEY_ENABLED:'true',VITE_PADDLE_CHECKOUT_ENABLED:'true',VITE_PADDLE_CLIENT_TOKEN:'test_synthetic',VITE_PADDLE_CHECKOUT_ORIGIN:origin}),
  'process.env.NODE_ENV':JSON.stringify('production')},plugins:[react(),{name:'offline-paddle-fixture',resolveId(id){if(id===input)return input;},load(id){if(id===input)return fixture;}}],
  build:{write:false,minify:false,lib:{entry:input,formats:['es']},rollupOptions:{output:{codeSplitting:false}}}});
const script=(Array.isArray(result)?result:[result]).flatMap(v=>v.output).find(v=>v.type==='chunk').code;
const browser=await chromium.launch({executablePath:chrome,headless:true}),checks=[];
try {
  for(const locale of ['en','ar']){
    const context=await browser.newContext(),page=await context.newPage(),unexpected=[],errors=[];
    let allowed=true,foreign=false,reads=0,sdkLoads=0;
    const messages=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing;
    page.setDefaultTimeout(8000);page.on('pageerror',e=>{errors.push(e.message);console.log('Synthetic browser error:',e.message);});
    await page.addInitScript(l=>localStorage.setItem('ceopro_locale',l),locale);
    await page.route('**/*',async route=>{
      const u=new URL(route.request().url());
      if(u.origin===origin&&u.pathname==='/billing/paddle-payment')return route.fulfill({contentType:'text/html',body:'<div id="root"></div><script type="module" src="/fixture.js"></script>'});
      if(u.href===origin+'/fixture.js')return route.fulfill({contentType:'text/javascript',body:script});
      if(u.href==='https://cdn.paddle.com/paddle/v2/paddle.js'){
        sdkLoads++;return route.fulfill({contentType:'text/javascript',body:`window.paddleCalls=[];window.Paddle={Environment:{set:v=>window.paddleCalls.push(['environment',v])},Initialize:v=>window.paddleCalls.push(['initialize',v]),Checkout:{open:v=>window.paddleCalls.push(['open',v])}};`});
      }
      if(u.pathname===`/billing/trial-journeys/${op}/checkout`){
        reads++;assert.equal(route.request().method(),'GET');
        return route.fulfill({status:allowed?200:403,contentType:'application/json',body:JSON.stringify(allowed?{operation_id:op,provider:'paddle',environment:'test',transaction_id:foreign?'txn_'+'b'.repeat(26):txn}:{detail:'Refused'})});
      }
      unexpected.push(u.href);return route.abort();
    });
    await page.goto(origin+`/billing/paddle-payment?trial_operation=${op}&_ptxn=${txn}`);
    const button=page.getByRole('button',{name:messages.subscriptionJourney.continue,exact:true});try{await button.waitFor();}catch(e){console.log(JSON.stringify({errors,unexpected,body:await page.locator('body').innerText()}));throw e;}
    assert.equal(sdkLoads,0);assert.equal(reads,0);checks.push(locale+': no SDK or API before explicit action');
    foreign=true;await button.click();await page.getByRole('alert').waitFor();assert.equal(sdkLoads,0);checks.push(locale+': mismatched URL transaction cannot load SDK');
    foreign=false;await button.click();try{await page.waitForFunction(()=>window.paddleCalls?.some(v=>v[0]==='open'));}catch(e){console.log(JSON.stringify({reads,sdkLoads,errors,unexpected,body:await page.locator('body').innerText()}));throw e;}
    const calls=await page.evaluate(()=>window.paddleCalls);assert.equal(calls[0][1],'sandbox');
    const options=calls.find(v=>v[0]==='open')[1];assert.equal(options.transactionId,txn);assert.equal(options.settings.locale,locale);
    assert.equal(options.settings.allowLogout,false);assert.deepEqual(options.settings.allowedPaymentMethods,['card']);assert.equal('items' in options,false);
    assert.equal(sdkLoads,1);checks.push(locale+': only exact server transaction opens sandbox card Checkout');
    allowed=false;await page.evaluate(()=>window.switchIdentity());await button.click();await page.getByRole('alert').waitFor();
    assert.equal((await page.evaluate(()=>window.paddleCalls)).filter(v=>v[0]==='open').length,1);
    assert.equal(reads,3);checks.push(locale+': identity switch and revoked server access prevent reopening');
    assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);await context.close();
  }
  console.log(JSON.stringify({status:'PASS',checks},null,2));
}finally{await browser.close();}

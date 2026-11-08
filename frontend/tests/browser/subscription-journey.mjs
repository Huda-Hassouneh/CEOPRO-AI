// Synthetic browser integration; every request intercepted, no API/provider.
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { build } from 'vite';
import react from '@vitejs/plugin-react';
import { chromium } from 'playwright-core';
const origin='http://127.0.0.1:19473',op='11111111-1111-4111-8111-111111111111';
const chrome=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'].find(existsSync);
assert.ok(chrome);
const fixture=`
import React from 'react';
import {createRoot} from 'react-dom/client';
import {MemoryRouter} from 'react-router-dom';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {I18nProvider} from './src/app/providers/I18nProvider.jsx';
import {loadLocale} from './src/shared/lib/i18n.js';
import {useAuthStore} from './src/features/auth/store/authStore.js';
import httpClient,{configureHttpClientAuth} from './src/shared/lib/httpClient.js';
import {SubscriptionJourney} from './src/features/billing/components/SubscriptionJourney.jsx';
import {useSubscription} from './src/features/billing/hooks/useSubscription.js';
httpClient.defaults.baseURL=location.origin;
configureHttpClientAuth({getAccessToken:()=> 'synthetic-offline-token'});
useAuthStore.setState({tenantId:'tenant-original',user:{id:'actor-original'}});
const client=new QueryClient();
window.refresh=()=>client.invalidateQueries();
window.switchIdentity=()=>useAuthStore.setState({tenantId:'tenant-other',user:{id:'actor-other'}});
function Rights(){const tenant=useAuthStore(s=>s.tenantId);const q=useSubscription(tenant);
return <output data-testid="rights">{!q.isError&&q.data?.hasAccess?'allowed':'denied'}</output>;}
loadLocale(localStorage.getItem('ceopro_locale')||'en').then(()=>{
createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}><I18nProvider><MemoryRouter>
<SubscriptionJourney plan="growth" period="monthly" /><Rights /></MemoryRouter></I18nProvider></QueryClientProvider>);
window.fixtureReady=true;
});`;
const input=resolve('.subscription-journey-offline.jsx');
const result=await build({configFile:false,envDir:false,logLevel:'silent',define:{
  'import.meta.env.VITE_RECURRING_JOURNEY_ENABLED':JSON.stringify('true'),
  'import.meta.env.VITE_RECURRING_CONSENT_ENABLED':JSON.stringify('true'),
  'import.meta.env.VITE_RECURRING_JOURNEY_PREVIEW_ENABLED':JSON.stringify('true'),
  'process.env.NODE_ENV':JSON.stringify('production')},plugins:[react(),{
    name:'offline-fixture',resolveId(id){if(id===input)return input;},load(id){if(id===input)return fixture;}}],
  build:{write:false,minify:false,lib:{entry:input,formats:['es']},rollupOptions:{output:{codeSplitting:false}}}});
const script=(Array.isArray(result)?result:[result]).flatMap(v=>v.output).find(v=>v.type==='chunk').code;
const browser=await chromium.launch({executablePath:chrome,headless:true}),checks=[];
try {
  for(const locale of ['en','ar']){
    const messages=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing;
    const context=await browser.newContext(),page=await context.newPage(),calls=[],errors=[],unexpected=[];
    let approved=false,accepted=false,confirmed=false,other=false,trialEnd=null;
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(l=>localStorage.setItem('ceopro_locale',l),locale);
    await page.route('**/*',async route=>{
      const req=route.request(),url=new URL(req.url());
      if(url.href===origin+'/')return route.fulfill({contentType:'text/html',body:'<div id="root"></div><script type="module" src="/fixture.js"></script>'});
      if(url.href===origin+'/fixture.js')return route.fulfill({contentType:'text/javascript',body:script});
      if(url.pathname==='/billing/subscription')return route.fulfill({contentType:'application/json',body:JSON.stringify({
        assigned:Boolean(trialEnd)&&!other,hasAccess:Boolean(trialEnd)&&!other,status:trialEnd?'trialing':'none',trialEndsAtExact:trialEnd})});
      if(!url.pathname.startsWith('/billing/trial-journeys')){unexpected.push(url.href);return route.abort();}
      calls.push({method:req.method(),path:url.pathname,body:req.postDataJSON()});
      const reply=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
      if(other)return reply({detail:'Unavailable'},404);
      if(url.pathname==='/billing/trial-journeys')return reply({operation_id:op,state:'reserved'});
      if(url.pathname.endsWith('/progress'))return reply({operation_id:op,state:confirmed?'confirmed':'consent_required'});
      const terms={renewal_amount:'59.000000000000001',currency:'USD',interval_months:1,trial_duration_days:14};
      if(url.pathname.endsWith('/consent/preparation'))return reply({operation_id:op,state:approved?'prepared':'pending_policy',
        missing_approvals:approved?[]:['agreement_text','trial_start_rule'],agreement_text:approved?'SYNTHETIC NOT LEGAL':null,
        policy_revision:approved?'synthetic-v1':null,commercial_terms:terms});
      if(url.pathname.endsWith('/consent/present'))return reply({state:'presented',presentation_id:op,challenge:'x'.repeat(72),policy_revision:'synthetic-v1'});
      if(url.pathname.endsWith('/consent/accept')){accepted=true;return reply({state:'accepted'});}
      if(url.pathname.endsWith('/advance'))return accepted?reply({state:'pending',reason:'trusted_verification_pending'}):reply({detail:'Missing consent'},409);
      if(url.pathname.endsWith('/cancellation'))return reply({state:'cancellation_recorded'});
      if(url.pathname===`/billing/trial-journeys/${op}`)return reply({operation_id:op,state:'eligible',reason:'reserved_terms_available',commercial_terms:terms});
      unexpected.push(url.href);return route.abort();
    });
    await page.goto(origin);await page.waitForFunction(()=>window.fixtureReady);
    await page.getByRole('button',{name:messages.subscriptionJourney.prepare,exact:true}).click();
    await page.getByText('59.000000000000001 USD',{exact:true}).first().waitFor();
    assert.equal(await page.getByRole('checkbox').isChecked(),false);
    assert.equal(await page.getByRole('checkbox').isEnabled(),false);
    assert.ok(calls.filter(c=>c.path.endsWith('/advance')).length===0);
    checks.push(locale+': plan selection creates one operation, frozen decimal, missing policy blocks unchecked consent');
    await page.getByRole('button',{name:messages.subscriptionJourney.continue,exact:true}).click();
    await page.getByRole('alert').waitFor();assert.equal(accepted,false);
    approved=true;await page.evaluate(()=>window.refresh());
    await page.getByRole('button',{name:messages.trialConsent.present,exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('input[type=checkbox]').disabled);
    assert.equal(await page.getByRole('checkbox').isChecked(),false);
    await page.getByRole('checkbox').check();await page.getByRole('button',{name:messages.trialConsent.accept,exact:true}).click();
    await page.getByText(messages.trialConsent.recorded,{exact:true}).waitFor();
    await page.getByRole('button',{name:messages.subscriptionJourney.continue,exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('[role=alert]'));
    assert.equal(new URL(page.url()).origin,origin);
    checks.push(locale+': explicit consent connects to advance; pending observation never redirects or grants access');
    confirmed=true;await page.evaluate(()=>window.refresh());
    await page.getByRole('button',{name:messages.subscriptionJourney.cancel,exact:true}).click();
    await page.getByText(messages.subscriptionJourney.canceled,{exact:true}).waitFor();
    checks.push(locale+': confirmed checkpoint exposes separate cancellation action');
    assert.equal(await page.getByTestId('rights').textContent(),'denied');
    trialEnd=new Date(Date.now()+1800).toISOString();await page.evaluate(()=>window.refresh());
    await page.waitForFunction(()=>document.querySelector('[data-testid=rights]').textContent==='allowed');
    await page.waitForFunction(()=>document.querySelector('[data-testid=rights]').textContent==='denied');
    checks.push(locale+': confirmation/redirect never grants; actual subscription cache expires at exact trial cutoff');
    other=true;await page.evaluate(()=>window.switchIdentity());
    await page.waitForFunction(()=>!document.body.textContent.includes('59.000000000000001'));
    assert.equal(await page.getByRole('checkbox').isChecked(),false);
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    assert.equal(calls.filter(c=>c.path==='/billing/trial-journeys').length,1);
    checks.push(locale+': account switch clears consent/terms; tenant-scoped read failure has no stale disclosure');
    await context.close();
  }
  console.log(JSON.stringify({status:'PASS',checks},null,2));
}finally{await browser.close();}

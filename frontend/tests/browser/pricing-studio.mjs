import { chromium } from 'playwright-core';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
const {APP_URL,API_URL,CHROMIUM_PATH,E2E_LOCALE,STUDIO_ROLE,STUDIO_SCENARIO}=process.env;
if(!APP_URL?.startsWith('http://127.0.0.1:')||!API_URL?.startsWith('http://127.0.0.1:'))throw new Error('Disposable loopback runtime required');
const t=JSON.parse(readFileSync(`src/assets/locales/${E2E_LOCALE}.json`,'utf8')).billing.pricingStudio;
const browser=await chromium.launch({executablePath:CHROMIUM_PATH,headless:true});
try{
 const page=await browser.newPage({viewport:{width:E2E_LOCALE==='ar'?480:1280,height:950}});
 page.setDefaultTimeout(10000);
 await page.addInitScript(locale=>localStorage.setItem('ceopro_locale',locale),E2E_LOCALE);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(APP_URL+'/tests/browser/pricing-studio.html');
 if(STUDIO_ROLE==='tenant'){
  // Existing Billing authorization may deny the entire page before its tabs.
  // Independently verify the Studio capability from this same browser identity.
  assert.equal(await page.evaluate(url=>fetch(url).then(r=>r.status),API_URL+'/platform/billing/pricing-studio'),403);
  assert.equal(await page.getByRole('button',{name:t.run,exact:true}).count(),0);
 }else{
  const row=page.getByRole('row').filter({has:page.getByRole('button',{name:t.analyzePricing,exact:true})}).first();
  await row.getByRole('button',{name:t.analyzePricing,exact:true}).click();
  await page.getByLabel(t.plan,{exact:true}).waitFor();
  await page.getByLabel(t.plan,{exact:true}).selectOption('starter');
  const request=()=>page.waitForResponse(r=>r.url()===API_URL+'/platform/billing/pricing-studio/analyze');
  let response=request();await page.getByRole('button',{name:t.run,exact:true}).click();
  const original=await(await response).json();
  if(STUDIO_SCENARIO==='missing'){
    assert.equal(original.pricing,null);assert.equal(original.status,'INCOMPLETE_DATA');
    await page.getByText(t.statuses.INCOMPLETE_DATA,{exact:true}).waitFor();
    await page.getByRole('alert').filter({hasText:t.warnings.COST_COVERAGE_MISSING}).waitFor();
  }else{
  assert.ok(original.pricing,JSON.stringify(original.warnings));
  await page.getByTestId('price-recommended').waitFor();assert.ok(await page.getByTestId('price-recommended').textContent());
  await page.getByLabel(t.mode,{exact:true}).selectOption('simulate');
  await page.getByLabel('ai_credits',{exact:true}).fill('9999');
  response=request();await page.getByRole('button',{name:t.run,exact:true}).click();
  const simulated=await(await response).json();assert.ok(Number(simulated.pricing.recommended)>Number(original.pricing.recommended));
  assert.equal(simulated.publishedPlan.feature_limits.find(f=>f.feature_code==='ai_credits').limit_value,original.publishedPlan.feature_limits.find(f=>f.feature_code==='ai_credits').limit_value);
  await page.getByText(t.evidence,{exact:true}).click();await page.getByText(t.observedSpend,{exact:true}).waitFor();
  await page.getByLabel(t.mode,{exact:true}).selectOption('analyze');
  response=request();await page.getByRole('button',{name:t.run,exact:true}).click();
  const again=await(await response).json();assert.deepEqual(again.plan,original.plan);assert.deepEqual(again.pricing,original.pricing);
  }
  assert.equal(await page.locator('.pricing-studio').getAttribute('dir'),E2E_LOCALE==='ar'?'rtl':'ltr');
 }
 assert.deepEqual(errors,[]);
 if(STUDIO_ROLE==='owner'){
  await page.locator('.pricing-studio').scrollIntoViewIfNeeded();
  await page.screenshot({path:process.env.SCREENSHOT_PATH});
 }
 console.log('PASS Pricing Studio '+STUDIO_ROLE+' '+E2E_LOCALE);
}finally{await browser.close();}

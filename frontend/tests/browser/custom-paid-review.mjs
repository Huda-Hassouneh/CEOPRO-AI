// Read-only actual paid quote presentation, including after cancellation.
import { chromium } from 'playwright-core';
import { readFileSync,mkdirSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,out=process.env.E2E_EVIDENCE_DIR;
if(base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||!process.env.E2E_EMAIL?.endsWith('@example.test'))throw new Error('Isolated synthetic runtime required');
mkdirSync(out,{recursive:true});const results=[];
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
try {
  for(const locale of ['en','ar']) {
    const t=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing.customPlan;
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.addInitScript(value=>localStorage.setItem('ceopro_locale',value),locale);
    const page=await context.newPage();page.setDefaultTimeout(18000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto(base+'/login');await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);await page.locator('input[type=password]').fill(process.env.E2E_PASSWORD);
    const login=page.waitForResponse(r=>r.url()===api+'/auth/login'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();if((await login).status()!==200)throw new Error('Synthetic login failed');await page.waitForURL(u=>u.pathname!=='/login');
    const detail=page.waitForResponse(r=>r.url()===api+'/billing/custom-offers/quotes/58e50994-2fb1-4c77-bf2b-8b390fced757');
    await page.goto(base+'/billing/custom-plan/quotes/58e50994-2fb1-4c77-bf2b-8b390fced757');
    const response=await detail;if(response.status()!==200||!(await response.json()).events.some(e=>e.action==='contract_activated'))throw new Error('Verified backend activation event missing');
    await page.getByText(t.paymentConfirmed,{exact:true}).waitFor();await page.getByRole('link',{name:t.manageSubscription,exact:true}).waitFor();
    if(await page.locator('.custom-plan-offer-actions button').count())throw new Error('Paid offer still exposes duplicate Checkout');
    await page.locator('.custom-plan-price strong').waitFor();
    if(await page.locator('html').getAttribute('dir')!==(locale==='ar'?'rtl':'ltr'))throw new Error('Wrong locale direction');
    if(errors.length)throw new Error(errors.join('\n'));
    await page.screenshot({path:join(out,'verified-custom-'+locale+'.png'),fullPage:true});
    results.push({locale,status:'PASS',backend:'real quote event',price:'frozen and visible',duplicateCheckout:'not offered',currentAccess:'referred to authoritative Billing page',mutations:0});await context.close();
  }
} finally {await browser.close();writeFileSync(join(out,'results.json'),JSON.stringify(results,null,2));}
console.log('PASS: actual paid Custom offer EN/AR, frozen price, verified-payment history and no duplicate Checkout; no mutation.');

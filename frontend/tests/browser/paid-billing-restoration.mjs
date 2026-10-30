// Read-only authenticated UI checks after real Stripe webhook activation.
import { chromium } from 'playwright-core';
import { readFileSync,writeFileSync,mkdirSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,evidence=process.env.E2E_EVIDENCE_DIR;
if(process.env.KEEL_REAL_STRIPE_TEST!=='YES'||base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||!process.env.E2E_EMAIL?.endsWith('@example.test'))throw new Error('Approved synthetic local runtime required');
mkdirSync(evidence,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const results=[];
try {
  for(const locale of ['en','ar']) {
    const texts=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8'));
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    await context.addInitScript(lang=>localStorage.setItem('ceopro_locale',lang),locale);
    const page=await context.newPage();page.setDefaultTimeout(20000);
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.goto(base+'/login');
    await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);await page.locator('input[type=password]').fill(process.env.E2E_PASSWORD);
    const login=page.waitForResponse(r=>r.url()===api+'/auth/login'&&r.request().method()==='POST');
    await page.locator('button[type=submit]').click();if((await login).status()!==200)throw new Error('Synthetic login failed');
    await page.waitForURL(url=>url.pathname!=='/login');
    await page.goto(base+'/billing');await page.locator('.billing-current-plan').waitFor();
    await page.locator('.billing-invoice-table tbody tr').first().waitFor();
    await page.screenshot({path:join(evidence,`paid-billing-${locale}.png`),fullPage:true});
    await page.goto(base+'/billing/plans');
    const current=page.locator('.ceopro-plan-card.is-current');await current.waitFor();
    if(await current.count()!==1||!await current.getByRole('button').isDisabled())throw new Error('Paid current-plan action is not uniquely disabled');
    await current.getByRole('button',{name:texts.billing.management.currentPlan,exact:true}).waitFor();
    await page.screenshot({path:join(evidence,`paid-current-plan-${locale}.png`),fullPage:true});
    const previewResponse=page.waitForResponse(r=>r.url()===api+'/billing/change-plan/preview');
    await page.goto(base+'/billing/checkout?plan=growth&period=monthly');
    const response=await previewResponse;if(response.status()!==200)throw new Error('Real plan-change preview failed');
    const preview=await response.json();
    if(!preview.eligible||preview.direction!=='upgrade'||preview.payment_policy!=='stripe_proration'||preview.immediate_amount!==null)throw new Error('Incorrect authoritative paid upgrade preview');
    await page.getByRole('region',{name:texts.billing.changePreview.title,exact:true}).waitFor();
    await page.screenshot({path:join(evidence,`paid-upgrade-review-${locale}.png`),fullPage:true});
    if(errors.length)throw new Error(errors.join('\n'));
    results.push({locale,status:'PASS',currentPlanButton:'disabled',historicalInvoice:'visible',preview:'real Python; immediate amount explicitly unknown; no mutation'});
    await context.close();
  }
} finally {await browser.close();writeFileSync(join(evidence,'paid-browser-results.json'),JSON.stringify(results,null,2));}
console.log('PASS: EN/AR actual paid Billing/invoice, disabled Current Plan and authoritative upgrade review; no subscription mutation.');

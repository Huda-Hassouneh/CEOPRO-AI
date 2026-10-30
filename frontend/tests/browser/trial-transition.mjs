// Real React -> FastAPI -> restricted PostgreSQL. Only provider HTTP is doubled
// by the explicit disposable backend fixture; no browser request is intercepted.
import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const { APP_URL:base, API_URL:api, E2E_EVIDENCE_DIR:evidence, E2E_EMAIL:email, E2E_PASSWORD:password }=process.env;
if(process.env.KEEL_TRIAL_BROWSER_FIXTURE!=='YES'||!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||!email?.endsWith('@keel-ci.example'))throw new Error('Explicit isolated offline fixture required');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const results=[];
try {
  for(const locale of ['en','ar']) {
    const text=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing;
    const context=await browser.newContext({viewport:{width:locale==='ar'?390:1440,height:1000}});
    await context.addInitScript(lang=>localStorage.setItem('ceopro_locale',lang),locale);
    const page=await context.newPage();page.setDefaultTimeout(20000);
    const errors=[];const calls=[];
    page.on('pageerror',error=>errors.push(error.message));
    page.on('response',r=>{if(new URL(r.url()).pathname.includes('/billing/'))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});
    const responseFor=(path,method)=>page.waitForResponse(r=>new URL(r.url()).pathname.endsWith(path)&&r.request().method()===method);
    await page.goto(base+'/login');
    await page.locator('input[type=email]').fill(email);await page.locator('input[type=password]').fill(password);
    const login=responseFor('/auth/login','POST');await page.locator('button[type=submit]').click();
    if((await login).status()!==200)throw new Error('Password login failed');
    await page.waitForURL(url=>url.pathname!=='/login');
    const token=await page.evaluate(()=>JSON.parse(localStorage.getItem('ceopro_auth_session')).accessToken);
    const get=async()=>{const r=await page.request.get(api+'/billing/subscription',{headers:{Authorization:`Bearer ${token}`}});if(r.status()!==200)throw new Error('Subscription read failed');return r.json();};
    const before=await get();
    if(before.status!=='trialing')throw new Error('Fixture must start in trial');
    await page.goto(base+'/billing');await page.locator('.billing-current-plan').waitFor();
    await page.locator('.billing-current-plan').getByText(text.management.status.trialing,{exact:true}).waitFor();
    await page.screenshot({path:join(evidence,`trial-before-${locale}.png`),fullPage:true});
    await page.goto(base+'/billing/checkout?plan=starter&period=monthly');
    await page.getByRole('region',{name:text.changePreview.title,exact:true}).waitFor();
    const changed=responseFor('/billing/change-plan','POST');
    await page.getByRole('button',{name:text.checkoutInApp.confirmChange,exact:true}).click();
    const change=await changed;if(change.status()!==200||(await change.json()).state!=='scheduled')throw new Error('Downgrade was not scheduled');
    await page.goto(base+'/billing');await page.locator('.billing-current-plan').waitFor();
    await page.reload();await page.locator('.billing-current-plan').getByText(text.management.status.trialing,{exact:true}).waitFor();
    const pending=await get();
    if(pending.scheduledChange?.planId!=='starter'||pending.status!==before.status||pending.renewsAt!==before.renewsAt||pending.periodEnd!==before.periodEnd||pending.trialEndsAt!==before.trialEndsAt)throw new Error('Scheduling changed trial or periods');
    await page.screenshot({path:join(evidence,`trial-pending-${locale}.png`),fullPage:true});
    await page.getByRole('button',{name:text.management.cancelScheduledChange,exact:true}).click();
    const cancelled=responseFor('/billing/scheduled-change','DELETE');
    const common=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).common;
    await page.getByRole('dialog').getByRole('button',{name:common.confirm,exact:true}).click();
    if((await cancelled).status()!==200)throw new Error('Cancellation failed');
    await page.reload();await page.locator('.billing-current-plan').getByText(text.management.status.trialing,{exact:true}).waitFor();
    const after=await get();
    if(after.scheduledChange||after.status!==before.status||after.renewsAt!==before.renewsAt||after.periodEnd!==before.periodEnd||after.trialEndsAt!==before.trialEndsAt)throw new Error('Cancellation changed trial or periods');
    if(await page.locator('html').getAttribute('dir')!==(locale==='ar'?'rtl':'ltr'))throw new Error('Locale direction mismatch');
    if(errors.length)throw new Error(errors.join('\n'));
    results.push({locale,status:'PASS',before:before.status,pending:pending.status,after:after.status,period:'unchanged',calls});
    await context.close();
  }
} finally {await browser.close();writeFileSync(join(evidence,'browser-results.json'),JSON.stringify(results,null,2));}
console.log('PASS: real browser EN desktop / AR mobile RTL; trial downgrade -> reload -> cancel -> reload; no paid period');

// Actual authorized synthetic Platform Owner -> existing Python financial supplement.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,out=process.env.E2E_EVIDENCE_DIR;
if(base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||process.env.E2E_ALLOW_SYNTHETIC_OWNER_APPROVAL!=='YES')throw new Error('Explicit disposable synthetic approval required');
mkdirSync(out,{recursive:true});const lp=join(out,'../positive-custom-resource-ledger.json'),ledger=JSON.parse(readFileSync(lp,'utf8'));
assert.equal(ledger.test_only_economics,true);
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050}});await context.addInitScript(()=>localStorage.setItem('ceopro_locale','en'));
const page=await context.newPage();page.setDefaultTimeout(20000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
try{
 await page.goto(base+'/login');await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);await page.locator('input[type=password]').fill(process.env.E2E_PASSWORD);
 const login=page.waitForResponse(r=>r.url()===api+'/auth/login'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();assert.equal((await login).status(),200);await page.waitForURL(u=>u.pathname!=='/login');
 await page.goto(base+'/platform/billing?python=1&tab=quotes&quote='+ledger.quote_id);await page.locator('.keel-platform-billing').waitFor();
 if(!ledger.browser_approved){
  const calculated=page.waitForResponse(r=>r.url()===api+'/platform/billing/custom-quotes/'+ledger.quote_id+'/calculate'&&r.request().method()==='POST');await page.getByRole('button',{name:'Calculate price',exact:true}).click();const result=await calculated;assert.equal(result.status(),200);const calculation=await result.json();assert.equal(calculation.pricingAvailable,true);assert.ok(Number(calculation.monthlyPrice)>0);ledger.calculated_monthly_price=calculation.monthlyPrice;ledger.calculation=calculation;
  writeFileSync(lp,JSON.stringify(ledger,null,2));await page.screenshot({path:join(out,'owner-calculated-positive-custom.png'),fullPage:true});
  await page.getByRole('button',{name:'Approve offer',exact:true}).click();await page.getByLabel('Approval reference',{exact:true}).fill('SYNTHETIC TEST ONLY '+ledger.run_id);
  page.once('dialog',d=>d.accept());const approval=page.waitForResponse(r=>r.url()===api+'/platform/billing/custom-quotes/'+ledger.quote_id+'/approve'&&r.request().method()==='POST');await page.getByRole('button',{name:'Confirm action',exact:true}).click();const approved=await approval;assert.equal(approved.status(),200);
  await page.getByRole('button',{name:'Calculate price',exact:true}).waitFor({state:'detached'});ledger.browser_approved=true;writeFileSync(lp,JSON.stringify(ledger,null,2));
 }
 await page.screenshot({path:join(out,'owner-approved-positive-custom.png'),fullPage:true});assert.deepEqual(errors,[]);
 console.log('PASS: legitimate Platform Owner login, real quote review, authoritative calculation and binding approval through the existing owner UI. No customer rights granted by these operations.');
}catch(error){await page.screenshot({path:join(out,'owner-custom-failure.png'),fullPage:true});writeFileSync(join(out,'failure.json'),JSON.stringify({error:error.message,path:new URL(page.url()).pathname,errors},null,2));throw error;}
finally{writeFileSync(join(out,'requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

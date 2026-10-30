// Real newly registered customer -> original onboarding -> Stripe TEST Checkout.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import {join} from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,out=process.env.E2E_EVIDENCE_DIR;
if(base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||process.env.KEEL_REAL_STRIPE_TEST!=='YES'||process.env.E2E_ALLOW_TEST_PAYMENT!=='YES')throw new Error('Isolated approved TEST runtime required');
mkdirSync(out,{recursive:true});
const t=JSON.parse(readFileSync('src/assets/locales/en.json','utf8'));
const stateFile=join(out,'browser-state.xml');
const persisted=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`$v=Import-Clixml -LiteralPath '${stateFile.replaceAll("'","''")}';[Console]::Write([Net.NetworkCredential]::new('',$v).Password)`],{encoding:'utf8'}));
const progressFile=join(out,'hosted-progress.json'),progress=existsSync(progressFile)?JSON.parse(readFileSync(progressFile,'utf8')):{account:'acct_1UESzuDvEnSheKuc',livemode:false,checkout_sessions:[]};
const save=()=>writeFileSync(progressFile,JSON.stringify(progress,null,2));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},storageState:persisted.storage});
await context.addInitScript(value=>{localStorage.setItem('ceopro_locale','en');for(const [k,v] of Object.entries(value||{}))sessionStorage.setItem(k,v);},persisted.session);
const page=await context.newPage();page.setDefaultTimeout(20000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
const checkpoint=async()=>execFileSync('powershell.exe',['-NoProfile','-File',process.env.E2E_PROTECT_SCRIPT,stateFile],{input:JSON.stringify({storage:await context.storageState(),session:await page.evaluate(()=>Object.fromEntries(Object.entries(sessionStorage)))}),encoding:'utf8'});
try{
 if(!progress.workspace_created){
  await page.goto(base+'/workspaces/new');await page.locator('.workspace-create').waitFor();
  await page.locator('.workspace-create input').fill(process.env.E2E_BUSINESS_NAME);await page.locator('.workspace-create select').nth(0).selectOption('US');await page.locator('.workspace-create select').nth(1).selectOption('USD');
  const created=page.waitForResponse(r=>r.url()===api+'/auth/workspaces'&&r.request().method()==='POST');await page.locator('.workspace-create button[type=submit]').click();assert.equal((await created).status(),201);await page.waitForURL(u=>u.pathname==='/onboarding/region');
  progress.workspace_created=true;await checkpoint();save();
 }
 await page.goto(base+'/onboarding');await page.waitForURL(u=>u.pathname!=='/onboarding');
 if(new URL(page.url()).pathname==='/onboarding/region'){await page.locator('#setup-country').selectOption('JO');await page.locator('#setup-city').selectOption('amman');await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL(u=>u.pathname==='/onboarding/industry');}
 if(new URL(page.url()).pathname==='/onboarding/industry'){await page.locator('input[name=industry]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL(u=>u.pathname==='/onboarding/business');}
 if(new URL(page.url()).pathname==='/onboarding/business'){await page.locator('input[name=business-size]').first().check();await page.locator('#annual-revenue').selectOption('under-100k');await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL(u=>u.pathname==='/onboarding/objectives');}
 if(new URL(page.url()).pathname==='/onboarding/objectives'){await page.locator('input[name=objectives]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();}
 await page.waitForURL(u=>u.pathname==='/onboarding/plan');await page.locator('.ceopro-plan-card').first().waitFor();
 const session=await page.evaluate(()=>JSON.parse(localStorage.getItem('ceopro_auth_session'))),r=await context.request.get(api+'/billing/subscription',{headers:{Authorization:'Bearer '+session.accessToken}});assert.equal(r.status(),200);const subscription=await r.json();assert.equal(subscription.trialAvailable,false);assert.equal(subscription.trialUsed,false);assert.equal(subscription.hasSubscription,false);assert.equal(subscription.hasAccess,false);
 progress.tenant_id=session.tenantId;progress.no_second_trial={status:'PASS',trialAvailable:false,trialUsed:false,hasSubscription:false,hasAccess:false};save();await checkpoint();
 await page.screenshot({path:join(out,'original-promotion-workspace-plans.png'),fullPage:true});console.log('PASS: actual existing-user workspace creation, separate original onboarding, no second per-person trial and no inherited paid access.');
}catch(error){await page.screenshot({path:join(out,'workspace-failure.png'),fullPage:true});writeFileSync(join(out,'workspace-failure.json'),JSON.stringify({error:error.message,path:new URL(page.url()).pathname,errors},null,2));throw error;}
finally{writeFileSync(join(out,'workspace-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

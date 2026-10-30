// Actual browser -> Python -> disposable PostgreSQL/Redis/Mailpit. No API mocks.
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { execFileSync } from 'node:child_process';
import { existsSync,mkdirSync,readFileSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,out=process.env.E2E_EVIDENCE_DIR;
if(process.env.E2E_ALLOW_SYNTHETIC_SIGNUP!=='YES'||base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||!process.env.E2E_EMAIL?.startsWith('keel-onboarding-')||!process.env.E2E_EMAIL?.endsWith('@example.test'))throw new Error('Explicit isolated fresh-signup fixture required');
mkdirSync(out,{recursive:true});
const t=JSON.parse(readFileSync('src/assets/locales/en.json','utf8'));
const stateFile=join(out,'browser-state.xml'),progressFile=join(out,'progress.json');
const progress=existsSync(progressFile)?JSON.parse(readFileSync(progressFile,'utf8')):{checks:[]};
const save=()=>writeFileSync(progressFile,JSON.stringify(progress,null,2));
const db=()=>JSON.parse(execFileSync(process.env.E2E_PYTHON_EXE,[process.env.E2E_DB_INSPECTOR],{encoding:'utf8',env:process.env}));
const protect=value=>execFileSync('powershell.exe',['-NoProfile','-File',process.env.E2E_PROTECT_SCRIPT,stateFile],{input:JSON.stringify(value),encoding:'utf8'});
let persisted;
if(existsSync(stateFile))persisted=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`$v=Import-Clixml -LiteralPath '${stateFile.replaceAll("'","''")}';[Console]::Write([Net.NetworkCredential]::new('',$v).Password)`],{encoding:'utf8'}));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},...(persisted?{storageState:persisted.storage}:{} )});
await context.addInitScript(value=>{localStorage.setItem('ceopro_locale','en');if(value)for(const [k,v] of Object.entries(value))sessionStorage.setItem(k,v);},persisted?.session);
const page=await context.newPage();page.setDefaultTimeout(18000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
const checkpoint=async()=>{protect({storage:await context.storageState(),session:await page.evaluate(()=>Object.fromEntries(Object.entries(sessionStorage)))});save();};
const fillCode=async code=>{for(let i=0;i<6;i++)await page.locator('input[inputmode=numeric]').nth(i).fill(code[i]);};
async function mailCode(exclude) {
  const deadline=Date.now()+12000;
  while(Date.now()<deadline) {
    const r=await fetch('http://127.0.0.1:8025/api/v1/messages?limit=50');assert.equal(r.status,200);
    const list=(await r.json()).messages;
    const message=list.find(m=>m.ID!==exclude&&m.To?.some(to=>to.Address?.toLowerCase()===process.env.E2E_EMAIL.toLowerCase()));
    if(message){const body=await (await fetch('http://127.0.0.1:8025/api/v1/message/'+message.ID)).json();const code=body.Text?.match(/\b(\d{6})\b/)?.[1];if(code)return {id:message.ID,code};}
    await new Promise(r=>setTimeout(r,200));
  }throw new Error('No matching synthetic verification email delivered');
}
try {
  if(!progress.registered) {
    const before=db();assert.equal(before.users.length,0);assert.equal(before.companies.length,0);
    await page.goto(base+'/signup');
    await page.locator('input[autocomplete=name]').fill('SYNTHETIC Fresh Onboarding');await page.locator('input[autocomplete=organization]').fill(process.env.E2E_BUSINESS_NAME);await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);
    await page.locator('select').nth(0).selectOption('US');await page.locator('select').nth(1).selectOption('USD');
    for(const input of await page.locator('input[type=password]').all())await input.fill(process.env.E2E_PASSWORD);
    await page.locator('input[type=checkbox]').check();
    const signup=page.waitForResponse(r=>r.url()===api+'/auth/signup'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();assert.equal((await signup).status(),202);
    await page.waitForURL(u=>u.pathname==='/verify-email');progress.registered=true;
    const pending=db();assert.equal(pending.users.length,0);assert.equal(pending.companies.length,0);assert.equal(pending.memberships.length,0);progress.checks.push({id:'ONB-001-pending',status:'PASS',database:pending});await checkpoint();
    await page.screenshot({path:join(out,'pending-email-verification.png'),fullPage:true});
  }
  if(!progress.verified) {
    await page.goto(base+'/verify-email');const first=await mailCode();
    if(!progress.invalidCodeTested){await fillCode(first.code==='000000'?'111111':'000000');const invalid=page.waitForResponse(r=>r.url()===api+'/auth/email/verify'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();assert.equal((await invalid).status(),400);assert.equal(db().users.length,0);progress.invalidCodeTested=true;progress.checks.push({id:'ONB-002-wrong-code',status:'PASS'});save();}
    const resend=page.waitForResponse(r=>r.url()===api+'/auth/email/resend-verification'&&r.request().method()==='POST');await page.getByRole('button',{name:t.auth.verifyEmail.resend,exact:true}).click();assert.equal((await resend).status(),200);const second=await mailCode(first.id);
    await fillCode(first.code);const old=page.waitForResponse(r=>r.url()===api+'/auth/email/verify'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();assert.equal((await old).status(),400);
    await fillCode(second.code);const verified=page.waitForResponse(r=>r.url()===api+'/auth/email/verify'&&r.request().method()==='POST');await page.locator('button[type=submit]').click();assert.equal((await verified).status(),200);
    await page.waitForURL(u=>u.pathname!=='/verify-email');progress.verified=true;progress.checks.push({id:'ONB-003-resend-invalidation',status:'PASS'});await checkpoint();
    const provisioned=db();assert.equal(provisioned.users.length,1);assert.equal(provisioned.companies.length,1);assert.equal(provisioned.memberships.length,1);assert.equal(provisioned.memberships[0].role,'owner');assert.equal(provisioned.users[0].verified,true);progress.identity=provisioned;progress.checks.push({id:'ONB-001-provisioning',status:'PASS'});save();
  }
  await page.goto(base+'/onboarding');
  if(!progress.setupFinished) {
    await page.waitForURL(u=>u.pathname!=='/onboarding');
    if(new URL(page.url()).pathname==='/onboarding/region') {
      await page.locator('#setup-country').selectOption('JO');await page.locator('#setup-city').selectOption('amman');
      await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();
      await page.waitForURL(u=>u.pathname==='/onboarding/industry');
      await page.reload();await page.locator('input[name=industry]').first().waitFor();
      await page.goto(base+'/onboarding/objectives');await page.waitForURL(u=>u.pathname==='/onboarding/industry');
    }
    if(new URL(page.url()).pathname==='/onboarding/industry') {
      await page.locator('input[name=industry]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();
      await page.waitForURL(u=>u.pathname==='/onboarding/business');
    }
    if(new URL(page.url()).pathname==='/onboarding/business') {
      await page.locator('input[name=business-size]').first().check();await page.locator('#annual-revenue').selectOption('under-100k');await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();
      await page.waitForURL(u=>u.pathname==='/onboarding/objectives');
    }
    if(new URL(page.url()).pathname==='/onboarding/objectives') {
      await page.locator('input[name=objectives]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();
    }
    await page.waitForURL(u=>u.pathname==='/onboarding/plan');progress.setupFinished=true;await checkpoint();
    progress.checks.push({id:'ONB-004-durable-resume-and-step-guard',status:'PASS'});save();
  }
  await page.waitForTimeout(1200);await page.screenshot({path:join(out,'after-company-setup.png'),fullPage:true});
  assert.equal(new URL(page.url()).pathname,'/onboarding/plan','Fresh customer must reach plan selection before dashboard');
  await page.locator('.ceopro-plan-card').first().waitFor();assert.equal(await page.locator('.ceopro-plan-card:not(.custom-plan-card)').count(),3);await page.locator('.ceopro-custom-plan-callout').waitFor();
  progress.checks.push({id:'ONB-010',status:'PASS',fixedCards:3,custom:true});save();console.log('PASS: fresh browser signup, no pre-verification identity, real Mailpit OTP/resend, atomic provisioning, company setup and four plan choices.');
}catch(error){progress.failure={error:error.message,url:page.url(),calls,errors};save();await page.screenshot({path:join(out,'failure.png'),fullPage:true});await checkpoint();throw error;}
finally{await browser.close();writeFileSync(join(out,'requests.json'),JSON.stringify({calls,errors},null,2));}

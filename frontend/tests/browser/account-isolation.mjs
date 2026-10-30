// Real browser -> restricted API -> disposable PostgreSQL/Redis/Mailpit.
import assert from 'node:assert/strict';
import { chromium } from 'playwright-core';
import { randomUUID } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL, mail=process.env.MAILPIT_URL, out=process.env.E2E_OUTPUT;
if(process.env.ISOLATED_ACCOUNT_TEST!=='YES'||!base?.startsWith('http://127.0.0.1:'))throw new Error('Disposable runner required');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true});
const checks=[];
const pass=(locale,name)=>{checks.push({locale,name,status:'PASS'});console.log('PASS '+locale+' '+name);};
const fixture=()=>({email:`identity-${randomUUID()}@example.test`,password:`Fixture!9aA-${randomUUID()}`});
const api=async(page,path,method='GET',data)=>{
 const token=await page.evaluate(()=>JSON.parse(localStorage.getItem('ceopro_auth_session')||'null')?.accessToken);
 return page.request.fetch(base+'/api'+path,{method,headers:{Authorization:'Bearer '+token},...(data?{data}:{})});
};
const state=async page=>{const r=await api(page,'/onboarding/state');assert.equal(r.status(),200);return r.json();};
const identity=page=>page.evaluate(()=>{const s=JSON.parse(localStorage.getItem('ceopro_auth_session'));return{user:s.user.id,tenant:s.tenantId};});
async function signup(page,account,t,navigate=true){
 if(navigate)await page.goto(base+'/signup');
 await page.locator('input[autocomplete=name]').fill('Synthetic Identity Fixture');await page.locator('input[autocomplete=organization]').fill('Synthetic Account Isolation');
 await page.locator('input[type=email]').fill(account.email);await page.locator('select').nth(0).selectOption('JO');await page.locator('select').nth(1).selectOption('JOD');
 for(const field of await page.locator('input[type=password]').all())await field.fill(account.password);
 await page.locator('input[type=checkbox]').check();await page.locator('button[type=submit]').click();await page.waitForURL('**/verify-email');
 let code;
 for(let i=0;i<30&&!code;i++){
  const list=await(await fetch(mail+'/api/v1/messages')).json();
  const msg=(list.messages||[]).find(m=>(m.To||[]).some(x=>x.Address===account.email));
  if(msg){const body=await(await fetch(mail+'/api/v1/message/'+msg.ID)).json();code=(body.Text||'').match(/\b(\d{6})\b/)?.[1];}
  if(!code)await new Promise(r=>setTimeout(r,200));
 }
 assert.ok(code,'Real OTP email must arrive');
 for(let i=0;i<6;i++)await page.locator('input[inputmode=numeric]').nth(i).fill(code[i]);
 await page.locator('button[type=submit]').click();await page.waitForURL('**/onboarding/region');await page.getByRole('heading',{name:t.onboarding.region.title}).waitFor();
}
async function finishOnboarding(page,t){
 await page.locator('#setup-country').selectOption('JO');await page.locator('#setup-city').selectOption('amman');
 await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL('**/onboarding/industry');
 await page.locator('input[name=industry]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL('**/onboarding/business');
 await page.locator('input[name=business-size]').first().check();await page.locator('#annual-revenue').selectOption('under-100k');await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL('**/onboarding/objectives');
 await page.locator('input[name=objectives]').first().check();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL('**/onboarding/plan');
 await page.getByRole('button',{name:t.onboarding.persistence.currentTrial,exact:true}).click();await page.waitForURL('**/onboarding/connect-data');
 await page.getByRole('button',{name:t.dataConnections.skip,exact:true}).click();await page.waitForURL('**/dashboard');
 assert.equal((await state(page)).isComplete,true);
}
async function logout(page){
 // Invoke the same production handler; avoids responsive account menu differences.
 await page.evaluate(async()=>{const {signOut}=await import('/src/shared/components/layout/signOut.js');const {useAuthStore}=await import('/src/features/auth/store/authStore.js');await signOut(useAuthStore.getState().clearSession,path=>history.pushState({},'',path));});
 await page.goto(base+'/login');
}
async function login(page,account){
 await page.goto(base+'/login');await page.locator('input[type=email]').fill(account.email);await page.locator('input[type=password]').fill(account.password);await page.locator('button[type=submit]').click();
}
try{
 for(const locale of ['en','ar']){
  const t=JSON.parse(readFileSync(new URL('../../src/assets/locales/'+locale+'.json',import.meta.url),'utf8'));
  const context=await browser.newContext({viewport:{width:locale==='ar'?390:1280,height:850}});
  await context.addInitScript(l=>localStorage.setItem('ceopro_locale',l),locale);
  const page=await context.newPage();page.setDefaultTimeout(20000);const a=fixture(),b=fixture(),fresh=fixture();
  // Preserve the SPA so A's still-fresh guard cache is present at logout/signup.
  await signup(page,a,t);await finishOnboarding(page,t);const aid=await identity(page);pass(locale,'A real signup OTP and six-step onboarding');
  await page.waitForFunction(async()=>{const {queryClient}=await import('/src/shared/lib/queryClient.js');const {useAuthStore}=await import('/src/features/auth/store/authStore.js');const s=useAuthStore.getState();return !!queryClient.getQueryData(['settings-company',s.tenantId,s.user?.id,'gate'])?.company.onboardingCompletedAt;});
  // Click the existing user menu logout in the SPA, retaining QueryClient.
  await page.getByRole('button',{name:t.businessShell.profile.label,exact:true}).click();
  await page.getByRole('menuitem',{name:t.businessShell.navigation.logout,exact:true}).click();
  await page.waitForURL('**/login');
  assert.equal(await page.evaluate(()=>localStorage.getItem('ceopro_auth_session')),null);
  assert.equal(await page.evaluate(async()=>{const {queryClient}=await import('/src/shared/lib/queryClient.js');return queryClient.getQueryCache().getAll().filter(q=>q.state.data!==undefined).length;}),0);
  // Normal in-app Signup link retains the same JS process and QueryClient.
  await page.getByRole('link',{name:t.auth.login.signup,exact:true}).click();
  // Signup helper normally navigates; stay in SPA here to exercise original bug.
  await signup(page,b,t,false);const bid=await identity(page);assert.notEqual(bid.user,aid.user);assert.notEqual(bid.tenant,aid.tenant);
  const bs=await state(page);assert.equal(bs.currentStep,1);assert.equal(bs.highestCompletedStep,0);assert.equal(bs.isComplete,false);
  const subscription=await(await api(page,'/billing/subscription')).json();assert.equal(subscription.hasSubscription,false);assert.equal(subscription.hasBillingAccount,false);assert.equal(subscription.source,'trial');
  assert.equal(await page.locator('html').getAttribute('dir'),locale==='ar'?'rtl':'ltr');pass(locale,'same SPA A logout B signup: own identity step 1 and own local trial; no Stripe mapping');
  // Full reload is independent from previous in-memory cache.
  await page.goto(base+'/dashboard');await page.waitForURL('**/onboarding/region');pass(locale,'B reload cannot bypass incomplete onboarding');
  await page.getByRole('heading',{name:t.onboarding.region.title}).waitFor();
  await page.screenshot({path:join(out,'new-user-'+locale+'.png'),fullPage:true});
  // Fail a real company read to verify the page cannot open on error.
  await page.route('**/api/settings/company',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Controlled test outage'})}));
  await page.goto(base+'/dashboard');await page.getByRole('alert').filter({hasText:t.settings.company.loadError}).waitFor();assert.equal(new URL(page.url()).pathname,'/dashboard');
  assert.equal(await page.getByRole('button',{name:t.businessShell.profile.label,exact:true}).count(),0);pass(locale,'company read outage fails closed with localized retry');await page.unroute('**/api/settings/company');
  await logout(page);await login(page,a);await page.waitForURL('**/dashboard');assert.deepEqual(await identity(page),aid);pass(locale,'existing A login returns dashboard without onboarding');
  const freshContext=await browser.newContext();await freshContext.addInitScript(l=>localStorage.setItem('ceopro_locale',l),locale);const fp=await freshContext.newPage();await signup(fp,fresh,t);assert.equal((await state(fp)).currentStep,1);pass(locale,'fresh browser signup equals same-browser B');
  await context.close();await freshContext.close();
 }
 writeFileSync(join(out,'account-isolation-results.json'),JSON.stringify({checks,externalStripe:'UNRUN; no provider credentials or mutations'},null,2));
}finally{await browser.close();}

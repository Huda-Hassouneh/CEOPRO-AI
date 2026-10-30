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
const progressFile=join(out,'../promotion-workspace-resource-ledger.json'),progress=existsSync(progressFile)?JSON.parse(readFileSync(progressFile,'utf8')):{account:'acct_1UESzuDvEnSheKuc',livemode:false,checkout_sessions:[]};
const save=()=>writeFileSync(progressFile,JSON.stringify(progress,null,2));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},storageState:persisted.storage});
await context.addInitScript(value=>{localStorage.setItem('ceopro_locale','en');for(const [k,v] of Object.entries(value||{}))sessionStorage.setItem(k,v);},persisted.session);
const page=await context.newPage();page.setDefaultTimeout(20000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
const checkpoint=async()=>execFileSync('powershell.exe',['-NoProfile','-File',process.env.E2E_PROTECT_SCRIPT,stateFile],{input:JSON.stringify({storage:await context.storageState(),session:await page.evaluate(()=>Object.fromEntries(Object.entries(sessionStorage)))}),encoding:'utf8'});
const resumeFile=join(out,'checkout-resume.xml');
const resume=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`$v=Import-Clixml -LiteralPath '${resumeFile.replaceAll("'","''")}';[Console]::Write([Net.NetworkCredential]::new('',$v).Password)`],{encoding:'utf8'}));
assert.equal(resume.session_id,progress.checkout_sessions.at(-1));
let actualCheckout;
await page.route(api+'/billing/checkout',async route=>{const response=await route.fetch();actualCheckout=await response.json();if(response.ok()&&actualCheckout.session_id?.startsWith('cs_test_')){if(!progress.checkout_sessions.includes(actualCheckout.session_id))progress.checkout_sessions.push(actualCheckout.session_id);save();}await route.fulfill({response});});
const auth=JSON.parse(persisted.storage.origins.find(o=>o.origin===base).localStorage.find(x=>x.name==='ceopro_auth_session').value),headers={Authorization:'Bearer '+auth.accessToken};
const unpaid=async()=>{const r=await context.request.get(api+'/billing/subscription',{headers});assert.equal(r.status(),200);const state=await r.json();assert.equal(state.hasAccess,false);return {hasAccess:state.hasAccess,status:state.status,hasSubscription:state.hasSubscription};};
async function review(){
 await page.goto(base+'/onboarding/plan');await page.locator('.ceopro-plan-card').first().waitFor();await page.locator('.ceopro-plan-card').first().getByRole('button').click();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();await page.waitForURL(u=>u.pathname==='/onboarding/plan/payment');
}
async function coupon(){
 await page.locator('.billing-coupon-block input').fill(progress.promotion_code);
 let valid=false;const end=Date.now()+12000;
 while(Date.now()<end&&!valid){const result=page.waitForResponse(r=>r.url()===api+'/billing/promotions/validate'&&r.request().method()==='POST');await page.locator('.billing-coupon-block button').click();const r=await result;assert.equal(r.status(),200);valid=(await r.json()).valid;if(!valid)await page.waitForTimeout(400);}
 assert.equal(valid,true);await page.locator('.billing-coupon-success').waitFor();
}
async function checkout(){const created=page.waitForResponse(r=>r.url()===api+'/billing/checkout'&&r.request().method()==='POST');await page.locator('.ceopro-payment-method button').click();const r=await created;assert.equal(r.status(),200);assert.ok(actualCheckout.session_id.startsWith('cs_test_'));await page.waitForURL(u=>u.hostname==='checkout.stripe.com');await page.waitForLoadState('domcontentloaded');await page.getByText('Card',{exact:true}).waitFor({timeout:45000});}
async function frame(){let found;const end=Date.now()+30000;while(Date.now()<end&&!found){for(const f of page.frames())if(await f.locator('#cardNumber,input[name=cardNumber],input[autocomplete=cc-number],#Field-numberInput').first().isVisible().catch(()=>false)){found=f;break;}if(!found)await page.waitForTimeout(200);}assert.ok(found,'Actual provider card form required');return found;}
async function card(number){
 let visible=false;for(const f of page.frames())if(await f.locator('#cardNumber,input[autocomplete=cc-number]').first().isVisible().catch(()=>false))visible=true;
 if(!visible){const label=page.getByText('Card',{exact:true});await label.waitFor();const box=await label.boundingBox();await page.mouse.click(box.x+box.width/2,box.y+box.height/2);}
 const f=await frame();await f.locator('#cardNumber,input[name=cardNumber],input[autocomplete=cc-number],#Field-numberInput').first().fill(number);await f.locator('#cardExpiry,input[name=cardExpiry],input[autocomplete=cc-exp],#Field-expiryInput').first().fill('1234');await f.locator('#cardCvc,input[name=cardCvc],input[autocomplete=cc-csc],#Field-cvcInput').first().fill('123');
 if(await page.locator('#billingName').count())await page.locator('#billingName').fill('SYNTHETIC KEEL onboarding');if(await page.locator('#billingCountry').count())await page.locator('#billingCountry').selectOption('US');if(await page.locator('#billingPostalCode').count())await page.locator('#billingPostalCode').fill('10001');for(const checkbox of await page.locator('input[type=checkbox]').all())if(await checkbox.isChecked())await checkbox.uncheck();
}
try{
 if(!progress.cancelled_retry){
  // Resume the exact existing session by a verified read-only lookup.
  assert.equal(resume.status,'open');assert.ok(resume.url.startsWith('https://checkout.stripe.com/'));
  await page.goto(resume.url);await page.getByText('Card',{exact:true}).waitFor({timeout:45000});await page.screenshot({path:join(out,'provider-before-cancel.png'),fullPage:true});
  let back=page.locator('a[href^="'+base+'/billing?checkout=cancelled"]');
  if(!await back.count())back=page.getByRole('button',{name:'Back',exact:true});
  if(!await back.count())back=page.locator('#backButton,.Header-backButton');
  if(!await back.count()){writeFileSync(join(out,'provider-back-controls.json'),JSON.stringify(await page.locator('a,button').evaluateAll(nodes=>nodes.map(n=>({tag:n.tagName,id:n.id,label:n.getAttribute('aria-label'),text:n.innerText,href:n.href?new URL(n.href).origin+new URL(n.href).pathname:null}))),null,2));throw Error('Inspect actual provider Back control');}
  await back.first().click();await page.waitForURL(u=>u.pathname==='/onboarding/plan/failed');await page.locator('.ceopro-subscription-result.is-failed').waitFor();await unpaid();await page.screenshot({path:join(out,'original-onboarding-cancel.png'),fullPage:true});
  const closed=page.waitForResponse(r=>r.url()===api+'/billing/checkout/cancel-pending'&&r.request().method()==='POST');await page.getByRole('button',{name:t.billing.result.failed.action,exact:true}).click();assert.equal((await closed).status(),200);await page.waitForURL(u=>u.pathname==='/onboarding/plan/payment');
  progress.cancelled_retry={status:'PASS',first_session:progress.checkout_sessions[0],rights_before_payment:false,original_failed_route:true,owned_pending_closed:true};save();await checkpoint();
 }
 if(!progress.hosted_paid){
  if(resume.status==='open'&&resume.session_id!==progress.cancelled_retry.first_session){
    await page.goto(resume.url);await page.getByText('Card',{exact:true}).waitFor({timeout:45000});
  }else{
    // The first session was explicitly expired above. This is the single
    // intended replacement; a recovery run resumes it instead of recreating.
    assert.equal(progress.checkout_sessions.length,1);
    await review();await coupon();await page.screenshot({path:join(out,'original-onboarding-promo-review.png'),fullPage:true});await checkout();
    assert.equal(progress.checkout_sessions.length,2);
  }
  if(!progress.decline){await card('4000000000000002');await page.locator('button[type=submit]').click();await page.getByText(/card (was|has been) declined|card declined/i).first().waitFor({timeout:30000});await page.screenshot({path:join(out,'stripe-real-decline.png'),fullPage:true});progress.decline={status:'PASS',before_payment:await unpaid()};save();}
  await card('4000002500003155');await page.locator('button[type=submit]').click();
  let challenge;const end=Date.now()+45000;
  while(Date.now()<end&&!challenge){for(const f of page.frames()){const complete=f.locator('#test-source-authorize-3ds').or(f.getByRole('button',{name:/^complete$|complete authentication|authorize|succeed/i}));if(await complete.first().isVisible().catch(()=>false)){challenge=complete.first();break;}}if(!challenge)await page.waitForTimeout(250);}
  if(!challenge){writeFileSync(join(out,'sca-controls.json'),JSON.stringify(await Promise.all(page.frames().map(async f=>({origin:new URL(f.url()).origin,controls:await f.locator('button,input').evaluateAll(nodes=>nodes.map(n=>({tag:n.tagName,id:n.id,label:n.getAttribute('aria-label'),text:n.innerText})))}))),null,2));throw Error('Actual Stripe TEST authentication challenge was not found');}
  progress.sca_before_auth=await unpaid();await page.screenshot({path:join(out,'stripe-real-sca-challenge.png'),fullPage:true});await challenge.click();
  await page.waitForURL(u=>u.origin===base,{timeout:60000});await page.waitForURL(u=>u.pathname==='/onboarding/plan/success',{timeout:60000});await page.locator('.ceopro-subscription-result.is-success').waitFor();await page.screenshot({path:join(out,'original-onboarding-confirmed-success.png'),fullPage:true});
  progress.hosted_paid={status:'BROWSER_COMPLETED_PROVIDER_RECONCILIATION_PENDING',original_success_route:true,sca_challenge_completed:true,at:new Date().toISOString()};save();
  await page.getByRole('button',{name:t.onboarding.paymentSuccess.continueSetup,exact:true}).click();await page.waitForURL(u=>u.pathname==='/onboarding/connect-data');const completed=page.waitForResponse(r=>r.url()===api+'/settings/company/onboarding/complete'&&r.request().method()==='POST');await page.getByRole('button',{name:t.dataConnections.skip,exact:true}).click();assert.equal((await completed).status(),200);await page.waitForURL(u=>u.pathname==='/dashboard');await page.reload();await page.waitForTimeout(1000);assert.equal(new URL(page.url()).pathname,'/dashboard');await checkpoint();progress.dashboard_after_payment={status:'PASS',reload:true};save();await page.screenshot({path:join(out,'promotion-paid-dashboard.png'),fullPage:true});
 }
 console.log('PASS: real hosted cancellation -> original failed result -> safe retry; real decline without rights; real 3DS challenge -> original verified success -> setup completion/dashboard. Provider invoice/discount verification remains separate.');
}catch(error){await page.screenshot({path:join(out,'promo-hosted-failure.png'),fullPage:true});writeFileSync(join(out,'promo-hosted-failure.json'),JSON.stringify({error:error.message,origin:new URL(page.url()).origin,path:new URL(page.url()).origin===base?new URL(page.url()).pathname:'<provider-path>',errors},null,2));throw error;}
finally{writeFileSync(join(out,'promotion-hosted-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

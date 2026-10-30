// Real newly registered customer -> original onboarding -> Stripe TEST Checkout.
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync,existsSync} from 'node:fs';
import {join} from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,out=process.env.E2E_EVIDENCE_DIR;
if(base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||process.env.KEEL_REAL_STRIPE_TEST!=='YES'||process.env.E2E_ALLOW_TEST_PAYMENT!=='YES')throw new Error('Isolated approved TEST runtime required');
mkdirSync(out,{recursive:true});
const _t=JSON.parse(readFileSync('src/assets/locales/en.json','utf8'));
const stateFile=join(out,'browser-state.xml');
const persisted=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`$v=Import-Clixml -LiteralPath '${stateFile.replaceAll("'","''")}';[Console]::Write([Net.NetworkCredential]::new('',$v).Password)`],{encoding:'utf8'}));
const progressFile=join(out,'hosted-progress.json'),progress=existsSync(progressFile)?JSON.parse(readFileSync(progressFile,'utf8')):{account:'acct_1UESzuDvEnSheKuc',livemode:false,checkout_sessions:[]};
const _save=()=>writeFileSync(progressFile,JSON.stringify(progress,null,2));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},storageState:persisted.storage});
await context.addInitScript(value=>{localStorage.setItem('ceopro_locale','en');for(const [k,v] of Object.entries(value||{}))sessionStorage.setItem(k,v);},persisted.session);
const page=await context.newPage();page.setDefaultTimeout(20000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
const checkpoint=async()=>execFileSync('powershell.exe',['-NoProfile','-File',process.env.E2E_PROTECT_SCRIPT,stateFile],{input:JSON.stringify({storage:await context.storageState(),session:await page.evaluate(()=>Object.fromEntries(Object.entries(sessionStorage)))}),encoding:'utf8'});
const lp=join(out,'../positive-custom-resource-ledger.json'),ledger=JSON.parse(readFileSync(lp,'utf8'));
assert.equal(ledger.browser_accepted,true);
let actualCheckout;
// Pass through the unmodified real Python response, capturing before navigation
// destroys Chrome's response-body handle. This supplies no mocked API data.
await page.route(api+'/billing/custom-offers/quotes/'+ledger.quote_id+'/checkout-attempts',async route=>{
 const response=await route.fetch();actualCheckout=await response.json();
 if(response.ok()&&actualCheckout.session_id?.startsWith('cs_test_')){
  if(!ledger.checkout_sessions.includes(actualCheckout.session_id))ledger.checkout_sessions.push(actualCheckout.session_id);writeFileSync(lp,JSON.stringify(ledger,null,2));
 }
 await route.fulfill({response});
});
try{
 await page.goto(base+'/billing/custom-plan/quotes/'+ledger.quote_id);await page.locator('.custom-plan-offer-actions').waitFor();
 await page.screenshot({path:join(out,'positive-custom-before-payment.png'),fullPage:true});
 const created=page.waitForResponse(r=>r.url()===api+'/billing/custom-offers/quotes/'+ledger.quote_id+'/checkout-attempts'&&r.request().method()==='POST');
 await page.locator('.custom-plan-offer-actions button').click();const response=await created;assert.equal(response.status(),200);const session=actualCheckout;
 assert.ok(session.session_id?.startsWith('cs_test_')&&session.url?.startsWith('https://checkout.stripe.com/'));
 if(!ledger.checkout_sessions.includes(session.session_id))ledger.checkout_sessions.push(session.session_id);writeFileSync(lp,JSON.stringify(ledger,null,2));
 await page.waitForURL(u=>u.hostname==='checkout.stripe.com');await page.waitForLoadState('domcontentloaded');
  const cardLabel=page.getByText('Card',{exact:true});
  await cardLabel.waitFor();
  const cardBounds=await cardLabel.boundingBox();
  if(!cardBounds)throw new Error('Visible Card choice has no bounds');
  // Stripe places its actual clickable cover over the visible label.
  await page.mouse.click(cardBounds.x+cardBounds.width/2,cardBounds.y+cardBounds.height/2);
  let cardFrame;
  const readyDeadline=Date.now()+45000;
  while(Date.now()<readyDeadline&&!cardFrame) {
    for(const frame of page.frames()) {
      if(await frame.locator('#cardNumber,input[name=cardNumber],input[autocomplete=cc-number],#Field-numberInput').first().isVisible().catch(()=>false)){cardFrame=frame;break;}
    }
    if(!cardFrame)await new Promise(resolve=>setTimeout(resolve,300));
  }
  const controls=[];
  for(const frame of page.frames())controls.push({origin:new URL(frame.url()).origin,controls:await frame.locator('input,select,button').evaluateAll(nodes=>nodes.map(node=>({tag:node.tagName,type:node.type,name:node.name,id:node.id,label:node.getAttribute('aria-label'),text:node.tagName==='BUTTON'?node.innerText:null})))});
  writeFileSync(join(out,'stripe-form-controls.json'),JSON.stringify(controls,null,2));
  await page.screenshot({path:join(out,'stripe-hosted-test.png'),fullPage:true});
  if(!cardFrame)throw new Error('Stripe hosted card form was not available; inspect captured provider state');
  if(process.env.E2E_ALLOW_TEST_PAYMENT!=='YES')throw new Error('Explicit TEST payment authorization required');
  {
    await cardFrame.locator('#cardNumber,input[name=cardNumber],input[autocomplete=cc-number],#Field-numberInput').first().fill('4242424242424242');
    await cardFrame.locator('#cardExpiry,input[name=cardExpiry],input[autocomplete=cc-exp],#Field-expiryInput').first().fill('1234');
    await cardFrame.locator('#cardCvc,input[name=cardCvc],input[autocomplete=cc-csc],#Field-cvcInput').first().fill('123');
    const name=page.locator('#billingName');if(await name.count())await name.fill('Synthetic KEEL Test');
    const country=page.locator('#billingCountry');if(await country.count())await country.selectOption('US');
    const postal=page.locator('#billingPostalCode');if(await postal.count())await postal.fill('10001');
    const save=page.locator('input[type=checkbox]');for(let i=0;i<await save.count();i++){const item=save.nth(i);if(await item.isChecked())await item.uncheck();}
    await page.locator('button[type=submit]').click();
    await page.waitForURL(url=>url.origin===base&&url.pathname==='/billing',{timeout:60000});
    await page.locator('.billing-current-plan').waitFor();await page.screenshot({path:join(out,'onboarding-stripe-return.png'),fullPage:true});
  }
  ledger.hosted_browser_return={origin:new URL(page.url()).origin,path:new URL(page.url()).pathname,at:new Date().toISOString(),verification:'PROVIDER_RECONCILIATION_PENDING'};writeFileSync(lp,JSON.stringify(ledger,null,2));await checkpoint();
  console.log('PASS: real accepted positive-credit Custom offer -> Stripe TEST hosted form -> correct KEEL billing origin. Provider reconciliation remains separate.');
}catch(error){await page.screenshot({path:join(out,'hosted-failure.png'),fullPage:true});writeFileSync(join(out,'hosted-failure.json'),JSON.stringify({error:error.message,origin:new URL(page.url()).origin,body:await page.locator('body').innerText(),errors},null,2));throw error;}
finally{writeFileSync(join(out,'hosted-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

// Real Stripe TEST hosted Checkout; requires explicit synthetic-fixture/payment flags.
import { chromium } from 'playwright-core';
import { readFileSync,writeFileSync,mkdirSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,evidence=process.env.E2E_EVIDENCE_DIR;
if(process.env.KEEL_REAL_STRIPE_TEST!=='YES'||base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||!process.env.E2E_EMAIL?.endsWith('@example.test'))throw new Error('Explicit approved disposable Stripe TEST runtime required');
mkdirSync(evidence,{recursive:true});
const ledgerPath=join(evidence,'../checkout-resource-ledger.json');
const ledger=JSON.parse(readFileSync(ledgerPath,'utf8'));
if(ledger.account!=='acct_1UESzuDvEnSheKuc'||ledger.livemode!==false)throw new Error('Unexpected Stripe ledger');
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050}});
const page=await context.newPage();page.setDefaultTimeout(20000);
const errors=[];page.on('pageerror',error=>errors.push(error.message));
let actualCheckout;
// Observe the real backend response before the app immediately leaves this origin.
// fetch/fulfill passes through its unmodified status, headers and body; no fixture response.
await page.route(api+'/billing/checkout',async route=>{
  const response=await route.fetch();
  actualCheckout=await response.json();
  if(response.ok()&&actualCheckout.session_id?.startsWith('cs_test_')) {
    if(!ledger.checkout_sessions.includes(actualCheckout.session_id))ledger.checkout_sessions.push(actualCheckout.session_id);
    writeFileSync(ledgerPath,JSON.stringify(ledger,null,2));
  }
  await route.fulfill({response});
});
try {
  await page.goto(base+'/login');
  await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);
  await page.locator('input[type=password]').fill(process.env.E2E_PASSWORD);
  const loggedIn=page.waitForResponse(r=>r.url()===api+'/auth/login'&&r.request().method()==='POST');
  await page.locator('button[type=submit]').click();
  if((await loggedIn).status()!==200)throw new Error('Actual synthetic login failed');
  await page.waitForURL(url=>url.pathname!=='/login');
  await page.goto(base+'/billing/checkout?plan=starter&period=monthly');
  await page.locator('.billing-upgrade-review').waitFor();
  await page.screenshot({path:join(evidence,'keel-before-checkout.png'),fullPage:true});
  const created=page.waitForResponse(r=>r.url()===api+'/billing/checkout'&&r.request().method()==='POST');
  await page.locator('.billing-payment-boundary button').first().click();
  const response=await created;
  if(!response.ok())throw new Error('KEEL Checkout HTTP '+response.status());
  const session=actualCheckout;
  if(!session.session_id?.startsWith('cs_test_')||!session.url?.startsWith('https://checkout.stripe.com/'))throw new Error('Refusing non-TEST hosted Checkout');
  if(!ledger.checkout_sessions.includes(session.session_id))ledger.checkout_sessions.push(session.session_id);
  writeFileSync(ledgerPath,JSON.stringify(ledger,null,2));
  await page.waitForURL(url=>url.hostname==='checkout.stripe.com');
  await page.waitForLoadState('domcontentloaded');
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
  writeFileSync(join(evidence,'stripe-form-controls.json'),JSON.stringify(controls,null,2));
  await page.screenshot({path:join(evidence,'stripe-hosted-test.png'),fullPage:true});
  if(!cardFrame)throw new Error('Stripe hosted card form was not available; inspect captured provider state');
  if(process.env.E2E_ALLOW_TEST_PAYMENT!=='YES') {
    console.log('Real TEST Checkout prepared through original KEEL review UI; provider form captured, no payment submitted.');
  } else {
    await cardFrame.locator('#cardNumber,input[name=cardNumber],input[autocomplete=cc-number],#Field-numberInput').first().fill('4242424242424242');
    await cardFrame.locator('#cardExpiry,input[name=cardExpiry],input[autocomplete=cc-exp],#Field-expiryInput').first().fill('1234');
    await cardFrame.locator('#cardCvc,input[name=cardCvc],input[autocomplete=cc-csc],#Field-cvcInput').first().fill('123');
    const name=page.locator('#billingName');if(await name.count())await name.fill('Synthetic KEEL Test');
    const country=page.locator('#billingCountry');if(await country.count())await country.selectOption('US');
    const postal=page.locator('#billingPostalCode');if(await postal.count())await postal.fill('10001');
    const save=page.locator('input[type=checkbox]');for(let i=0;i<await save.count();i++){const item=save.nth(i);if(await item.isChecked())await item.uncheck();}
    await page.locator('button[type=submit]').click();
    await page.waitForURL(url=>url.origin===base&&url.pathname==='/billing',{timeout:60000});
    await page.locator('.billing-current-plan').waitFor();
    await page.screenshot({path:join(evidence,'keel-after-hosted-test.png'),fullPage:true});
    ledger.hosted_browser_return={origin:new URL(page.url()).origin,path:new URL(page.url()).pathname,completedAt:new Date().toISOString(),paymentVerification:'PENDING_PROVIDER_AND_SIGNED_WEBHOOK_RECONCILIATION'};
    writeFileSync(ledgerPath,JSON.stringify(ledger,null,2));
    console.log('Hosted TEST form submitted and returned to correct KEEL origin; provider/webhook/database verification still required.');
  }
} catch(error) {
  await page.screenshot({path:join(evidence,'failure.png'),fullPage:true});
  // Avoid persisting the bearer-like hosted Checkout URL or customer credentials.
  writeFileSync(join(evidence,'failure.json'),JSON.stringify({origin:new URL(page.url()).origin,text:await page.locator('body').innerText(),error:error.message,errors},null,2));
  throw error;
} finally {await browser.close();}

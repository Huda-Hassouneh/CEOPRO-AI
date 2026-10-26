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
const _save=()=>writeFileSync(progressFile,JSON.stringify(progress,null,2));
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const context=await browser.newContext({viewport:{width:1440,height:1050},storageState:persisted.storage});
await context.addInitScript(value=>{localStorage.setItem('ceopro_locale','en');for(const [k,v] of Object.entries(value||{}))sessionStorage.setItem(k,v);},persisted.session);
const page=await context.newPage();page.setDefaultTimeout(20000);const calls=[],errors=[];
page.on('response',r=>{if(r.url().startsWith(api))calls.push({path:new URL(r.url()).pathname,status:r.status(),method:r.request().method()});});page.on('pageerror',e=>errors.push(e.message));
const checkpoint=async()=>execFileSync('powershell.exe',['-NoProfile','-File',process.env.E2E_PROTECT_SCRIPT,stateFile],{input:JSON.stringify({storage:await context.storageState(),session:await page.evaluate(()=>Object.fromEntries(Object.entries(sessionStorage)))}),encoding:'utf8'});
const lp=join(out,'../positive-custom-resource-ledger.json'),ledger=JSON.parse(readFileSync(lp,'utf8'));
try{
 assert.equal(ledger.test_only_economics,true);assert.equal(ledger.browser_approved,true);
 await page.goto(base+'/billing/custom-plan/quotes/'+ledger.quote_id+'?returnTo='+encodeURIComponent('/onboarding/plan'));
 await page.locator('.custom-plan-price').waitFor();
 if(!ledger.browser_accepted){
  const accepted=page.waitForResponse(r=>r.url()===api+'/billing/custom-offers/quotes/'+ledger.quote_id+'/accept'&&r.request().method()==='POST');await page.getByRole('button',{name:t.billing.customPlan.acceptOffer,exact:true}).click();assert.equal((await accepted).status(),200);ledger.browser_accepted=true;writeFileSync(lp,JSON.stringify(ledger,null,2));
 }
 await page.reload();await page.getByText(t.billing.customPlan.acceptedNotActivated,{exact:true}).waitFor();await page.locator('.custom-plan-price').waitFor();
 await page.screenshot({path:join(out,'accepted-positive-custom-no-activation.png'),fullPage:true});await checkpoint();
 console.log('PASS: customer retrieved actual frozen offer, accepted it and reloaded; UI explicitly states no activation yet.');
}catch(error){await page.screenshot({path:join(out,'custom-accept-failure.png'),fullPage:true});throw error;}
finally{writeFileSync(join(out,'custom-accept-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

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
 await page.goto(base+'/dashboard');await page.waitForURL(u=>u.pathname==='/onboarding/connect-data');await page.locator('.ceopro-data-source-card').first().waitFor();
 assert.equal(await page.locator('.ceopro-data-source-card').count(),4);
 await page.screenshot({path:join(out,'original-onboarding-connections.png'),fullPage:true});
 const completed=page.waitForResponse(r=>r.url()===api+'/settings/company/onboarding/complete'&&r.request().method()==='POST');
 await page.getByRole('button',{name:t.dataConnections.skip,exact:true}).click();assert.equal((await completed).status(),200);
 await page.waitForURL(u=>u.pathname==='/dashboard');await page.waitForTimeout(1500);assert.equal(new URL(page.url()).pathname,'/dashboard');
 await page.reload();await page.waitForTimeout(1500);assert.equal(new URL(page.url()).pathname,'/dashboard');assert.deepEqual(errors,[]);
 await page.screenshot({path:join(out,'fresh-paid-dashboard.png'),fullPage:true});
 await checkpoint();progress.dashboard={status:'PASS',reload:true,setup_complete:true,original_connection_cards:4,errors};save();
 console.log('PASS: exact original connection cards -> explicit skip -> server-verified completion -> paid dashboard -> reload; no redirect loop or console errors.');
}catch(error){await page.screenshot({path:join(out,'finish-failure.png'),fullPage:true});writeFileSync(join(out,'finish-failure.json'),JSON.stringify({error:error.message,path:new URL(page.url()).pathname,errors},null,2));throw error;}
finally{writeFileSync(join(out,'finish-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

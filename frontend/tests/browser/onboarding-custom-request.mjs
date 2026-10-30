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
 await page.goto(base+'/onboarding/plan');await page.locator('.ceopro-custom-plan-callout button').click();await page.getByRole('button',{name:t.onboarding.common.continue,exact:true}).click();
 await page.waitForURL(u=>u.pathname==='/onboarding/plan/custom');await page.locator('.ceopro-custom-feature-card').first().waitFor();
 const quantities={data_credits:100,ai_credits:50,connected_data_sources:2,tracked_products:10,rag_assistant:1000,web_searches:5,tracked_competitors:2,document_storage_mb:64,document_extraction:8,team_seats:2,monthly_reports:1,marketing_image_generation:1,sentiment_analysis:10};
 for(const code of ['market_intelligence','demand_prediction','competitor_management'])await page.getByRole('checkbox',{name:t.billing.modules[code],exact:true}).check();
 for(const [code,value] of Object.entries(quantities)){
   const label=t.billing.customPlan.featureNames[code];assert.ok(label,'Real catalog label '+code);
   await page.getByRole('checkbox',{name:label,exact:true}).check();await page.getByRole('textbox',{name:label,exact:true}).fill(String(value));
 }
 await page.locator('.ceopro-custom-feature-card__configuration select').selectOption('10080');
 const validated=page.waitForResponse(r=>r.url()===api+'/billing/custom-offers/configuration/validate'&&r.request().method()==='POST');await page.getByRole('button',{name:t.billing.customPlan.validate,exact:true}).click();assert.equal((await validated).status(),200);
 await page.locator('.custom-plan-price-unavailable').waitFor();await page.screenshot({path:join(out,'positive-custom-manual-review.png'),fullPage:true});
 const submitted=page.waitForResponse(r=>r.url()===api+'/billing/custom-offers/quotes'&&r.request().method()==='POST');await page.getByRole('button',{name:t.billing.customPlan.requestQuote,exact:true}).click();const response=await submitted;assert.equal(response.status(),201);const quote=await response.json();
 assert.ok(quote.quote_id);progress.quote_id=quote.quote_id;progress.configuration={limits:quantities,enabled_features:['market_intelligence','demand_prediction','competitor_management'],refresh_frequency:'weekly'};save();
 await page.waitForURL(u=>u.pathname==='/billing/custom-plan/quotes/'+quote.quote_id);await page.reload();await page.getByText(t.billing.customPlan.status.submitted,{exact:true}).waitFor();
 await page.screenshot({path:join(out,'positive-custom-saved-request.png'),fullPage:true});await checkpoint();
 console.log('PASS: real original onboarding Custom route, positive Data/AI allowances, monitoring cadence, Python validation, honest unavailable pricing, durable manual request and reload retrieval.');
}catch(error){await page.screenshot({path:join(out,'custom-request-failure.png'),fullPage:true});writeFileSync(join(out,'custom-request-failure.json'),JSON.stringify({error:error.message,path:new URL(page.url()).pathname,errors},null,2));throw error;}
finally{writeFileSync(join(out,'custom-request-requests.json'),JSON.stringify({calls,errors},null,2));await browser.close();}

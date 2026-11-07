// State-only regression against an isolated KEEL API with a configured copy
// provider (an explicit offline copy fixture is also suitable). Persists two
// synthetic campaigns; use a disposable tenant. No images are generated.
// APP_URL=... E2E_EMAIL=... E2E_PASSWORD=... MARKETING_EVIDENCE=<private-dir>
// [CHROMIUM_PATH=...] node tests/browser/marketing-campaign-state.mjs
import assert from 'node:assert/strict';
import {chromium} from 'playwright-core';
import {writeFileSync} from 'node:fs';
const {APP_URL:base,E2E_EMAIL:email,E2E_PASSWORD:password,MARKETING_EVIDENCE:output}=process.env;
if(!base||!email||!password||!output)throw new Error('Set APP_URL, E2E_EMAIL, E2E_PASSWORD and a private MARKETING_EVIDENCE directory.');
const browser=await chromium.launch({...process.env.CHROMIUM_PATH?{executablePath:process.env.CHROMIUM_PATH}:{channel:'chrome'},headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});page.setDefaultTimeout(30000);
// Explicit state-isolation regression: real React, POSTs, and persisted GETs.
// Image boundaries are doubled deliberately; this is not image acceptance.
const captures=[];
try{
 await page.route('**/api/marketing/image-capacity',r=>r.fulfill({json:{available:true,workers:1}}));
 await page.route('**/api/marketing/campaigns/*/image-batches',r=>r.fulfill({json:{jobs:[],fixture:'image generation excluded'}}));
 await page.route('**/api/marketing/campaigns',async r=>{if(r.request().method()==='POST')captures.push(r.request().postDataJSON());await r.continue();});
 await page.goto(base+'/login');await page.locator('input[type=email]').fill(email);await page.locator('input[type=password]').fill(password);await page.locator('button[type=submit]').click();await page.waitForURL(u=>!u.pathname.startsWith('/login'));
 await page.goto(base+'/marketing');await page.locator('[role=tablist] [role=tab]').nth(2).click();
 const description=page.locator('textarea.mk-textarea').first();const options=page.locator('details.studio-more');await options.locator('summary').click();
 const audience=options.locator('input').first(),theme=options.locator('select').first(),notes=options.locator('textarea');
 const snapshot=async()=>({description:await description.inputValue(),audience:await audience.inputValue(),theme:await theme.inputValue(),notes:await notes.inputValue()});
 const create=async()=>{const response=page.waitForResponse(r=>r.request().method()==='POST'&&new URL(r.url()).pathname==='/api/marketing/campaigns',{timeout:180000});await page.locator('.studio-generate button').click();const r=await response;assert.equal(r.status(),200);const result=await r.json();await page.locator('.studio-editor').waitFor();return result;};
 await description.fill('STATE_FIXTURE_A: MarkerCup-A. Explicit test-only offer: 10% discount until 2026-12-20.');
 await page.locator('[role=radio]').nth(3).click();await page.locator('.mk-chips button').first().waitFor();await page.locator('.mk-chips button').first().click();
 await page.locator('[role=radio]').nth(1).click();
 await audience.fill('AUDIENCE_A_ZEBRA');await theme.selectOption('BOLD_PROMOTIONAL');await notes.fill('NOTES_A_MAGENTA; explicit test-only 10% offer.');
 const visibleA=await snapshot();await page.screenshot({path:output+'/state-a.png',fullPage:true});const A=await create();
 await description.fill('STATE_FIXTURE_B: Plain SeasonalCup-B for a clean fresh seasonal scenario.');await page.locator('[role=radio]').nth(3).click();
 await audience.fill('');await theme.selectOption('');await notes.fill('');
 const selected=page.locator('.mk-chips button[aria-pressed=true]');if(await selected.count())await selected.click();
 const visibleB=await snapshot();await page.screenshot({path:output+'/state-b-cleared.png',fullPage:true});const B=await create();
 const auth=await page.evaluate(()=>JSON.parse(localStorage.getItem('ceopro_auth_session')));
 const read=async id=>(await(await page.request.get(base+'/api/marketing/campaigns/'+id,{headers:{Authorization:'Bearer '+auth.accessToken}})).json());
 const savedA=await read(A.campaign_id),savedB=await read(B.campaign_id);
 assert.equal(savedB.creative_theme,'SEASONAL');assert.ok(!savedB.custom_creative_prompt);assert.equal(visibleB.audience,'');assert.equal(visibleB.theme,'');assert.equal(visibleB.notes,'');
 assert.ok(!JSON.stringify(captures[1]).match(/AUDIENCE_A|NOTES_A|MAGENTA|ZEBRA|10%|BOLD_PROMOTIONAL|Occasion:/));
 const report={result:'PASS',visibleA,visibleB,payloadA:captures[0],payloadB:captures[1],persistedA:{campaign_id:savedA.campaign_id,source_text:savedA.source_text,creative_theme:savedA.creative_theme,custom_creative_prompt:savedA.custom_creative_prompt},persistedB:{campaign_id:savedB.campaign_id,source_text:savedB.source_text,creative_theme:savedB.creative_theme,custom_creative_prompt:savedB.custom_creative_prompt},hiddenOccasionInOffer:Boolean(captures[0].custom_creative_prompt?.includes('Occasion:')),copy:process.env.MARKETING_COPY_MODE||'server-configured copy provider',images:'capacity and queue boundaries doubled; no image generation'};
 assert.equal(report.hiddenOccasionInOffer,false,'An occasion hidden by a goal change must not be submitted');
 writeFileSync(output+'/state-result.json',JSON.stringify(report,null,2));console.log(JSON.stringify({state_isolation:'PASS',hiddenOccasionInOffer:report.hiddenOccasionInOffer,campaigns:2}));
}catch(e){writeFileSync(output+'/state-error.private.txt',String(e));await page.screenshot({path:output+'/state-blocked.png',fullPage:true});console.log('BLOCKED: state browser verification; private evidence retained');process.exitCode=1;}finally{await browser.close();}

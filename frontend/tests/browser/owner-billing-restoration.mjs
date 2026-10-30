// Actual authorized synthetic Platform Owner; read-only browser verification.
import { chromium } from 'playwright-core';
import { mkdirSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL,evidence=process.env.E2E_EVIDENCE_DIR;
if(base!=='http://127.0.0.1:5204'||api!=='http://127.0.0.1:8024'||!process.env.E2E_EMAIL?.endsWith('@example.test'))throw new Error('Identified isolated owner runtime required');
mkdirSync(evidence,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const page=await browser.newPage({viewport:{width:1440,height:1050}});page.setDefaultTimeout(18000);
const errors=[],calls=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('response',r=>{if(r.url().startsWith(api+'/platform/'))calls.push({path:new URL(r.url()).pathname,status:r.status()});});
try {
  await page.goto(base+'/login');
  await page.locator('input[type=email]').fill(process.env.E2E_EMAIL);
  await page.locator('input[type=password]').fill(process.env.E2E_PASSWORD);
  const login=page.waitForResponse(r=>r.url()===api+'/auth/login'&&r.request().method()==='POST');
  await page.locator('button[type=submit]').click();if((await login).status()!==200)throw new Error('Real owner login failed');
  await page.waitForURL(u=>u.pathname!=='/login');
  await page.goto(base+'/platform/billing?python=1&tab=pricing');
  await page.waitForURL(u=>u.pathname==='/admin/billing');
  if(new URL(page.url()).searchParams.get('tab')!=='pricing'||new URL(page.url()).searchParams.get('python')!=='1')throw new Error('Historical owner redirect discarded pricing/review query');
  await page.getByRole('heading',{name:'Pricing policies',exact:true}).waitFor();
  await page.locator('details summary').filter({hasText:'Policy 1'}).click();
  await page.getByText('OWNER AUTHORIZED SYNTHETIC TEST ONLY',{exact:false}).first().waitFor();
  checks.push('Real owner policy details reachable through historical link');
  for(const tab of ['plans','custom-plans','custom-quotes','promos','features','plan-features','subscriptions']) {
    await page.goto(base+'/admin/billing?tab='+tab);
    await page.locator('.billing-catalog-page').waitFor();
    await page.waitForTimeout(650);
    await page.screenshot({path:join(evidence,'owner-original-'+tab+'.png'),fullPage:true});
    checks.push('Original owner tab '+tab);
  }
  for(const tab of ['pricing','costs','quotes','contracts','subscriptions','audit']) {
    await page.goto(base+'/platform/billing?python=1&tab='+tab+(tab==='quotes'?'&quote=58e50994-2fb1-4c77-bf2b-8b390fced757':''));
    await page.locator('.keel-platform').waitFor();await page.waitForTimeout(650);
    await page.screenshot({path:join(evidence,'owner-python-'+tab+'.png'),fullPage:true});
    checks.push('Existing Python administration '+tab);
  }
  await page.locator('.pa-language').click();
  await page.waitForFunction(()=>document.documentElement.dir==='rtl');
  for(const tab of ['plans','custom-quotes','promos']) {
    await page.goto(base+'/admin/billing?tab='+tab);await page.locator('.billing-catalog-page').waitFor();await page.waitForTimeout(650);
    await page.screenshot({path:join(evidence,'owner-original-'+tab+'-ar.png'),fullPage:true});
    checks.push('Original owner Arabic RTL '+tab);
  }
  if(errors.length||calls.some(c=>c.status>=400))throw new Error('Owner browser errors: '+JSON.stringify({errors,calls:calls.filter(c=>c.status>=400)}));
  writeFileSync(join(evidence,'results.json'),JSON.stringify({status:'PASS',checks,calls,errors,financialMutations:0},null,2));
  console.log('PASS: actual owner login, original billing tabs and versioned policy/quote/cost deep links; real APIs, no browser financial mutation.');
} catch(error) {
  await page.screenshot({path:join(evidence,'failure.png'),fullPage:true});
  writeFileSync(join(evidence,'failure.json'),JSON.stringify({url:page.url(),error:error.message,errors,calls,text:await page.locator('body').innerText()},null,2));throw error;
} finally {await browser.close();}

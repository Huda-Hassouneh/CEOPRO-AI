// Actual local React/FastAPI checks. Quote creation requires a separate one-request approval flag.
import { chromium } from 'playwright-core';
import { readFileSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { resolve } from 'node:path';
const base=process.env.APP_URL,api=process.env.API_URL;
if(process.env.KEEL_BILLING_BROWSER_FIXTURE!=='YES'||!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||'')||!/^http:\/\/127\.0\.0\.1:\d+$/.test(api||''))throw new Error('Explicit disposable local billing runtime required');
const email=process.env.E2E_EMAIL,password=process.env.E2E_PASSWORD;
if(!email?.endsWith('@example.test')||!password)throw new Error('Synthetic billing fixture credentials required');
const evidence=process.env.E2E_EVIDENCE_DIR;
mkdirSync(evidence,{recursive:true});
const quoteEvidence=resolve(evidence,'approved-one-quote.json');
const quoteIntent=resolve(evidence,'approved-one-quote-intent.json');
let savedQuote=existsSync(quoteEvidence)?JSON.parse(readFileSync(quoteEvidence,'utf8')):null;
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const results=[],requests=[];
let currentPage;
try {
  for(const {locale,width} of [{locale:'en',width:1440},{locale:'ar',width:1440},{locale:'en',width:390}]) {
    const texts=JSON.parse(readFileSync(resolve('src/assets/locales/'+locale+'.json'),'utf8'));
    const context=await browser.newContext({viewport:{width,height:1000}});
    await context.addInitScript((lang)=>localStorage.setItem('ceopro_locale',lang),locale);
    const page=await context.newPage();currentPage=page;page.setDefaultTimeout(15000);
    const errors=[];
    page.on('pageerror',(error)=>errors.push(error.message));
    page.on('response',(response)=>{
      if(response.url().startsWith(api)) {
        const path=new URL(response.url()).pathname;
        if(path.startsWith('/billing'))requests.push({variant:`${locale}-${width}`,path,status:response.status(),method:response.request().method()});
        if(response.status()>=500)errors.push(`API ${response.status()} ${path}`);
      }
    });
    await page.goto(base+'/login');
    await page.locator('input[type=email]').fill(email);
    await page.locator('input[type=password]').fill(password);
    const login=page.waitForResponse((response)=>response.url()===api+'/auth/login'&&response.request().method()==='POST');
    await page.locator('button[type=submit]').click();
    if((await login).status()!==200)throw new Error('Real browser password login failed');
    await page.waitForURL((url)=>url.pathname!=='/login');
    await page.goto(base+'/billing');
    await page.locator('.billing-current-plan').waitFor();
    if(await page.locator('html').getAttribute('dir')!==(locale==='ar'?'rtl':'ltr'))throw new Error('Incorrect locale direction');
    await page.screenshot({path:resolve(evidence,`billing-${locale}-${width}.png`),fullPage:true});
    results.push({screen:'billing',locale,width,status:'PASS',authentication:'actual password login'});
    await page.goto(base+'/billing/plans');
    await page.locator('.ceopro-plan-card').first().waitFor();
    if(await page.locator('.ceopro-plan-card').count()!==3)throw new Error('Expected three fixed-plan cards');
    await page.locator('.ceopro-custom-plan-callout').waitFor();
    await page.locator('[aria-controls="billing-plan-comparison"]').click();
    await page.locator('.billing-comparison-table').waitFor();
    if(await page.locator('.billing-comparison-table thead th').count()!==5)throw new Error('Comparison must contain three fixed plans and exactly one Custom column');
    await page.screenshot({path:resolve(evidence,`plans-${locale}-${width}.png`),fullPage:true});
    results.push({screen:'plans-and-comparison',locale,width,status:'PASS',fixedCards:3,customEntry:true});
    await page.goto(base+'/billing/checkout?plan=growth&period=monthly');
    await page.locator('.billing-upgrade-review').waitFor();
    await page.screenshot({path:resolve(evidence,`review-${locale}-${width}.png`),fullPage:true});
    results.push({screen:'subscription-review',locale,width,status:'PASS'});
    await page.goto(base+'/billing/custom-plan');
    await page.locator('.ceopro-custom-feature-card').first().waitFor();
    const label=texts.billing.customPlan.featureNames.connected_data_sources;
    const checkbox=page.getByRole('checkbox',{name:label,exact:true});
    await checkbox.check();
    const article=page.locator('.ceopro-custom-feature-card').filter({has:checkbox});
    await article.getByRole('textbox').fill('10');
    await article.getByRole('textbox').press('Tab');
    const validated=page.waitForResponse((response)=>response.url()===api+'/billing/custom-offers/configuration/validate');
    await page.getByRole('button',{name:texts.billing.customPlan.validate,exact:true}).click();
    if((await validated).status()!==200)throw new Error('Real configuration validation failed');
    await page.getByText(texts.billing.customPlan.priceUnavailable,{exact:true}).waitFor();
    await page.screenshot({path:resolve(evidence,`custom-${locale}-${width}.png`),fullPage:true});
    results.push({screen:'original-custom-controls',locale,width,status:'PASS',quantity:10,pricing:'unavailable/manual review'});
    if(!savedQuote&&process.env.E2E_QUOTE_APPROVED_ONCE==='YES') {
      if(existsSync(quoteIntent))throw new Error('Prior quote submission intent exists: reconcile it before any retry');
      writeFileSync(quoteIntent,JSON.stringify({createdAt:new Date().toISOString(),purpose:'Owner approved exactly one synthetic manual-review request'}));
      const submitted=page.waitForResponse((response)=>response.url()===api+'/billing/custom-offers/quotes'&&response.request().method()==='POST');
      await page.getByRole('button',{name:texts.billing.customPlan.requestQuote,exact:true}).click();
      const response=await submitted;
      if(!response.ok())throw new Error('Quote submission HTTP '+response.status());
      const quote=await response.json();
      if(!quote.quote_id)throw new Error('Quote response lacks durable identity');
      savedQuote={quoteId:quote.quote_id,createdAt:new Date().toISOString(),purpose:'SYNTHETIC_MANUAL_REVIEW_ONLY'};
      writeFileSync(quoteEvidence,JSON.stringify(savedQuote,null,2));
    }
    if(savedQuote) {
      await page.goto(base+'/billing/custom-plan/quotes/'+encodeURIComponent(savedQuote.quoteId));
      await page.locator('.custom-plan-offer-status h2').waitFor();
      await page.reload();
      await page.getByText(texts.billing.customPlan.reviewPending,{exact:true}).waitFor();
      await page.screenshot({path:resolve(evidence,`quote-${locale}-${width}.png`),fullPage:true});
      results.push({screen:'durable-quote-retrieval',locale,width,status:'PASS',quoteId:savedQuote.quoteId,state:'submitted; no offer approval, Checkout or paid grants'});
      await page.goto(base+'/billing/custom-plan');
      await page.getByText(texts.billing.customPlan.quoteReference.replace('{{id}}',savedQuote.quoteId).replace('{id}',savedQuote.quoteId),{exact:true}).waitFor();
    } else {
    await page.reload();
    await page.getByText(texts.billing.customPlan.noRequests,{exact:true}).waitFor();
    results.push({screen:'customer-quote-list',locale,width,status:'PASS',state:'empty; no browser quote mutation'});
    }
    const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
    if(overflow)errors.push('Page overflows horizontally');
    if(errors.length)throw new Error(errors.join('\n'));
    await context.close();
  }
} catch(error) {
  if(currentPage&&!currentPage.isClosed()) {
    await currentPage.screenshot({path:resolve(evidence,'failure.png'),fullPage:true});
    writeFileSync(resolve(evidence,'failure.json'),JSON.stringify({url:currentPage.url(),text:await currentPage.locator('body').innerText(),error:error.message},null,2));
  }
  throw error;
} finally {
  await browser.close();
  writeFileSync(resolve(evidence,'browser-results.json'),JSON.stringify({results,requests},null,2));
}
console.log(`PASS: ${results.length} real browser checks; English/Arabic/RTL/mobile; quote=${savedQuote?.quoteId||'not submitted'}; no payment mutations.`);

// Real original owner UI -> Python -> restricted PostgreSQL. No mocked API.
import {chromium} from 'playwright-core';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const {APP_URL:base,E2E_PASSWORD:password,E2E_OUTPUT:output}=process.env;
if(process.env.KEEL_OWNER_BROWSER_ISOLATED!=='YES'||!/^http:\/\/127\.0\.0\.1:\d+$/.test(base||''))throw new Error('Identified disposable owner runtime required');
const fixture=JSON.parse(readFileSync(process.env.E2E_FIXTURE_FILE,'utf8'));
const messages=JSON.parse(readFileSync('src/assets/locales/en.json','utf8'));
const t=k=>k.split('.').reduce((v,p)=>v?.[p],messages)||k;
const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
const page=await browser.newPage({viewport:{width:1440,height:1100}});page.setDefaultTimeout(20000);
const calls=[],checks=[],errors=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('console',m=>{if(m.type()==='error' && /uncontrolled input|controlled input/.test(m.text()))errors.push(m.text());});
page.on('response',r=>{const u=new URL(r.url());if(u.pathname.startsWith('/api/platform/billing'))calls.push({path:u.pathname,status:r.status(),method:r.request().method()});});
const request=async(path,action,status=200)=>{const wait=page.waitForResponse(r=>new URL(r.url()).pathname==='/api'+path&&r.request().method()!=='GET');await action();const r=await wait;if(r.status()!==status)throw new Error(path+' HTTP '+r.status()+' '+await r.text());return r.json();};
const login=async role=>{
 await page.goto(base+'/login');await page.locator('input[type=email]').fill(fixture[role].email);await page.locator('input[type=password]').fill(password);
 let wait=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login');await page.locator('button[type=submit]').click();let response=await wait;
 if(response.status()===409&&role==='owner'){
   wait=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/auth/login');await page.getByRole('button',{name:/KEEL Platform/}).click();response=await wait;
 }
 if(response.status()!==200)throw new Error('Login failed: '+response.status());await page.waitForURL(u=>u.pathname!=='/login');
};
const fill=async(key,value,scope=page)=>scope.getByLabel(t(key),{exact:true}).fill(String(value));
const btn=(key,scope=page)=>scope.getByRole('button',{name:t(key),exact:true});
try{
 await login('owner');
 await page.goto(base+'/platform/billing?tab=custom-quotes');await page.waitForURL(u=>u.pathname==='/admin/billing');
 await page.getByRole('heading',{name:t('billing.catalog.customPlans.pricingPolicy.title'),exact:true}).waitFor();
 checks.push('Original shell, historical redirect and policy panel');
 await fill('billing.catalog.customPlans.targetMargin',25);await fill('billing.catalog.customPlans.pricingPolicy.fixedPlatformFee',0);await fill('billing.catalog.customPlans.pricingPolicy.monthlyInfrastructure',0);await fill('billing.catalog.customPlans.activeTenants',1);await fill('billing.catalog.customPlans.pricingPolicy.roundingIncrement','0.01');await fill('billing.catalog.legacyRestoration.approvalEvidence','SYNTHETIC TEST ONLY ? not production pricing');
 await btn('billing.catalog.customPlans.pricingPolicy.save').click();
 const policy=await request('/platform/billing/custom-plan-pricing/policies',()=>btn('common.confirm',page.getByRole('dialog')).click(),201);
 checks.push('Original policy save creates real draft');
 await btn('billing.catalog.customPlans.vendorRates.create').click();
 let dialog=page.getByRole('dialog');
 await dialog.getByLabel(t('billing.catalog.fields.feature'),{exact:true}).selectOption('connected_data_sources');
 await dialog.getByLabel(t('billing.catalog.customPlans.vendorRates.draftPolicy'),{exact:true}).selectOption(policy.policy_version_id);
 await fill('billing.catalog.customPlans.vendorRates.vendor','synthetic-provider',dialog);await fill('billing.catalog.customPlans.vendorRates.service','source-month',dialog);await fill('billing.catalog.customPlans.vendorRates.unit','request',dialog);await fill('billing.catalog.customPlans.vendorRates.unitCost',1,dialog);
 await fill('billing.catalog.customPlans.vendorRates.source','SYNTHETIC TEST ONLY ? controlled fixture',dialog);
 await fill('billing.catalog.customPlans.vendorRates.verifiedAt',new Date().toISOString().slice(0,10),dialog);await fill('billing.catalog.customPlans.vendorRates.effectiveFrom',new Date(Date.now()-120000).toISOString().slice(0,16),dialog);
 await dialog.getByLabel(t('billing.catalog.fields.status'),{exact:true}).selectOption('confirmed');
 await request('/platform/billing/custom-plan-pricing/vendor-rates',()=>btn('common.save',dialog).click(),201);
 await page.getByRole('dialog').waitFor({state:'hidden'});await page.getByRole('cell',{name:'synthetic-provider',exact:true}).waitFor();checks.push('Original Vendor Rate form persists and refreshes');
 await fill('billing.catalog.legacyRestoration.approvalEvidence','SYNTHETIC activation evidence');
 await btn('billing.catalog.legacyRestoration.activate').click();await request('/platform/billing/custom-plan-pricing/policies/'+policy.policy_version_id+'/activate',()=>btn('common.confirm',page.getByRole('dialog')).click());checks.push('Explicit policy activation through original section');
 await btn('billing.catalog.customPlans.create').click();dialog=page.getByRole('dialog');
 await dialog.locator('select').first().selectOption(fixture.customer.tenant_id);
 await dialog.locator('input[maxlength="50"]').first().fill('SYNTHETIC quote');await dialog.locator('input[maxlength="50"]').nth(1).fill('\u0639\u0631\u0636 \u062a\u062c\u0631\u064a\u0628\u064a');
 await btn('common.continue',dialog).click();
 // Canonical labels come from the real feature catalog rather than the code.
 const cards=dialog.locator('.billing-custom-plan-feature-row');let sourceCard;
 for(let i=0;i<await cards.count();i++){const card=cards.nth(i);const text=await card.innerText();if(/connected[ _]data[ _]sources/i.test(text)){sourceCard=card;break;}}
 if(!sourceCard)throw new Error('Connected-source feature card absent');
 await sourceCard.getByRole('checkbox').check();await sourceCard.getByLabel(t('billing.catalog.fields.limit'),{exact:true}).fill('10');if(!await sourceCard.getByLabel(t('billing.catalog.customPlans.estimatedUsage'),{exact:true}).isDisabled())throw new Error('Estimated usage must be server-derived');
 await btn('common.continue',dialog).click();
 if(!await dialog.getByLabel(t('billing.catalog.customPlans.targetMargin'),{exact:true}).isDisabled())throw new Error('Client margin override must remain disabled');
 await btn('common.continue',dialog).click();
 const made=await request('/platform/billing/custom-quotes',()=>btn('billing.catalog.customPlans.createQuote',dialog).click(),201);
 await page.getByRole('dialog').waitFor({state:'hidden'});await page.getByText('SYNTHETIC quote',{exact:true}).waitFor();
 checks.push('Original four-step quote creation and real Python calculation');
 const quoteId=made.quote_id;const quoteRow=page.getByRole('row').filter({hasText:'SYNTHETIC quote'});
 await btn('billing.catalog.customPlans.approve',quoteRow).click();dialog=page.getByRole('dialog');
 if(!await dialog.getByLabel(t('billing.catalog.customPlans.finalPrice'),{exact:true}).isDisabled())throw new Error('Frozen final price must not be editable');
 await fill('billing.catalog.fields.approvalReference','SYNTHETIC BROWSER APPROVAL',dialog);
 await request('/platform/billing/custom-quotes/'+quoteId+'/approve',()=>btn('billing.catalog.customPlans.approve',dialog).click());await page.getByRole('dialog').waitFor({state:'hidden'});
 await btn('billing.catalog.customPlans.review',quoteRow).click();dialog=page.getByRole('dialog');await dialog.getByText('SYNTHETIC quote',{exact:true}).waitFor();
 await dialog.getByText(t('billing.catalog.legacyRestoration.pricingEvidence'),{exact:true}).click();await dialog.getByText('calculationHash',{exact:false}).first().waitFor();
 await page.screenshot({path:resolve(output,'original-quote-review-en.png'),fullPage:true});await btn('common.close',dialog).click();checks.push('Frozen-price approval and in-place evidence review');
 // Draft-only promotion actions: no activation or provider resources.
 await page.goto(base+'/admin/billing?tab=promos');
 await btn('billing.catalog.promos.create').click();dialog=page.getByRole('dialog');
 await fill('billing.catalog.fields.code','SYNTH_BROWSER',dialog);
 await fill('billing.catalog.fields.discountValue',10,dialog);
 await fill('billing.catalog.fields.maxUses',3,dialog);
 await fill('billing.catalog.fields.maxUsesPerUser',1,dialog);
 await request('/platform/billing/promotions',()=>btn('common.save',dialog).click(),201);
 await page.getByRole('dialog').waitFor({state:'hidden'});
 let promoRow=page.getByRole('row').filter({hasText:'SYNTH_BROWSER'});
 await btn('common.edit',promoRow).click();dialog=page.getByRole('dialog');
 await fill('billing.catalog.fields.discountValue',11,dialog);
 const editResponse=page.waitForResponse(r=>new URL(r.url()).pathname.startsWith('/api/platform/billing/promotions/')&&r.request().method()==='PATCH');
 await btn('common.save',dialog).click();const saved=await editResponse;
 if(saved.status()!==200)throw new Error('Draft edit failed: '+saved.status());
 await page.getByRole('dialog').waitFor({state:'hidden'});await page.reload();
 promoRow=page.getByRole('row').filter({hasText:'SYNTH_BROWSER'});await promoRow.waitFor();
 await btn('common.edit',promoRow).click();dialog=page.getByRole('dialog');
 if(await dialog.getByLabel(t('billing.catalog.fields.discountValue'),{exact:true}).inputValue()!=='11')throw new Error('Draft discount did not persist');
 await btn('common.cancel',dialog).click();
 checks.push('Promotion draft create/edit/reload without provider activation');
 await page.goto(base+'/admin/billing?tab=features');
 const featureRow=page.getByRole('row').filter({hasText:/connected[ _]data[ _]sources/i});
 await btn('common.edit',featureRow).click();dialog=page.getByRole('dialog');
 await fill('billing.catalog.fields.name','SYNTHETIC source allowance',dialog);
 await request('/platform/billing/feature-catalog/connected_data_sources',()=>btn('common.save',dialog).click());
 await page.getByRole('dialog').waitFor({state:'hidden'});await page.reload();
 await page.getByRole('cell',{name:'SYNTHETIC source allowance',exact:true}).waitFor();
 checks.push('Canonical feature label persists through original form and refresh');
 await page.goto(base+'/admin/billing?tab=plan-features');
 await page.getByLabel(t('billing.catalog.fields.plan'),{exact:true}).selectOption('starter');
 const allowanceRow=page.getByRole('row').filter({hasText:'SYNTHETIC source allowance'});
 await allowanceRow.locator('input[type=number]').fill('5');
 await request('/platform/billing/plans/starter/features',()=>btn('common.save',allowanceRow).click());
 await page.reload();await page.getByLabel(t('billing.catalog.fields.plan'),{exact:true}).selectOption('starter');
 if(await page.getByRole('row').filter({hasText:'SYNTHETIC source allowance'}).locator('input[type=number]').inputValue()!=='5')throw new Error('Plan quota did not persist');
 checks.push('Supported plan quota persists through original form and refresh');
 for(const locale of ['en','ar'])for(const width of [1440,390]){
   await page.setViewportSize({width,height:1100});await page.evaluate(lang=>localStorage.setItem('ceopro_locale',lang),locale);
   for(const tab of ['plans','custom-plans','custom-quotes','promos','features','plan-features','subscriptions']){
     await page.goto(base+'/admin/billing?tab='+tab);await page.locator('.billing-catalog-page').waitFor();await page.waitForTimeout(400);await page.screenshot({path:resolve(output,`owner-${tab}-${locale}-${width}.png`),fullPage:true});
     if(await page.locator('html').getAttribute('dir')!==(locale==='ar'?'rtl':'ltr'))throw new Error('Incorrect locale direction');
   }checks.push(`${locale}/${width}: seven original tabs`);
 }
 await page.setViewportSize({width:1440,height:1100});
 // Real tenant-owner password session must not gain global owner privileges.
 await page.evaluate(()=>localStorage.clear());await login('customer');
 await page.goto(base+'/admin/billing');await page.waitForTimeout(800);
 if(await page.locator('.billing-catalog-page').count())throw new Error('Tenant Owner reached global billing');
 checks.push('Tenant Owner denied original global owner UI');
 if(calls.some(c=>c.status>=500))throw new Error('Owner API failed: '+JSON.stringify(calls.filter(c=>c.status>=500)));
 if(errors.length)throw new Error(errors.join('\n'));
 writeFileSync(resolve(output,'owner-browser.json'),JSON.stringify({status:'PASS',checks,calls,errors,quote_id:quoteId,stripe_operations:0},null,2));console.log('PASS: '+checks.length+' real original owner workflows; no Stripe operation.');
}catch(e){await page.screenshot({path:resolve(output,'failure.png'),fullPage:true});writeFileSync(resolve(output,'failure.json'),JSON.stringify({error:e.message,url:page.url(),text:await page.locator('body').innerText(),calls,checks,errors},null,2));throw e;}finally{await browser.close();}

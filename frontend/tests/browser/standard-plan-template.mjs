// Production UI -> actual restricted disposable API (started by pytest).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const locale=process.env.E2E_LOCALE || 'en';
const messages=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8'));
const t=key=>key.split('.').reduce((v,k)=>v?.[k],messages);
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH});
const issues=[];
try {
  const context=await browser.newContext({viewport:{width:Number(process.env.E2E_WIDTH),height:1000}});
  await context.addInitScript(v=>localStorage.setItem('ceopro_locale',v),locale);
  const page=await context.newPage();
  await page.route('**/favicon.ico',route=>route.fulfill({status:204}));
  page.on('pageerror',e=>issues.push(e.message));
  page.on('response',r=>{if(r.status()>=400)issues.push(`${r.status()} ${r.url()}`);});
  page.on('console',m=>{if(['error','warning'].includes(m.type()))issues.push(m.text());});
  await page.goto(process.env.APP_URL+'/tests/browser/standard-plan-creation.html');
  await page.getByRole('button',{name:t('billing.catalog.plans.create'),exact:true}).click();
  const dialog=page.getByRole('dialog');
  const templates=dialog.getByLabel(t('billing.catalog.templates.select'),{exact:true});
  await templates.selectOption('growth');
  await dialog.getByText(t('billing.catalog.templates.included'),{exact:true}).click();
  const catalog=await (await context.request.get(process.env.API_URL+'/platform/billing/plan-templates')).json();
  for(const c of catalog.categories)await dialog.getByRole('heading',{name:locale==='ar'?c.label_ar:c.label_en,exact:true}).waitFor();
  const key=`browser_template_${locale}_${Date.now()}`;
  for(const [name,value] of [['billing.catalog.plans.planKey',key],['billing.catalog.fields.name',key],
    ['billing.catalog.fields.nameAr',key+'_ar'],['billing.catalog.plans.monthlyPriceUsd','87.21'],
    ['billing.catalog.plans.auditReason','Synthetic disposable browser template verification']]) {
    await dialog.getByLabel(t(name),{exact:true}).fill(value);
  }
  assert.equal(await dialog.getByLabel(t('billing.catalog.plans.planKey'),{exact:true}).getAttribute('dir'),'ltr');
  assert.equal(await dialog.evaluate(e=>getComputedStyle(e).direction),locale==='ar'?'rtl':'ltr');
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  const bounds=await dialog.evaluate(e=>({width:e.clientWidth,scroll:e.scrollWidth,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}));
  assert.ok(bounds.scroll<=bounds.width+1&&bounds.left>=0&&bounds.right<=Number(process.env.E2E_WIDTH));
  await page.screenshot({path:process.env.SCREENSHOT_PATH.replace('.png','-form.png')});
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/platform/billing/plans')&&r.request().method()==='POST');
  await dialog.getByRole('button',{name:t('billing.catalog.plans.saveDraft'),exact:true}).click();
  const response=await responsePromise;
  assert.equal(response.status(),201,await response.text());
  assert.equal((await response.json()).is_active,false);
  await dialog.waitFor({state:'hidden'});
  const nav=page.locator('.billing-catalog-tabs nav');
  await nav.getByRole('link',{name:t('billing.catalog.tabs.planFeatures'),exact:true}).click();
  await page.getByLabel(t('billing.catalog.fields.plan'),{exact:true}).selectOption(key);
  for(const c of catalog.categories)await page.getByRole('heading',{name:locale==='ar'?c.label_ar:c.label_en,exact:true}).waitFor();
  const ai=catalog.features.find(f=>f.key==='ai_credits');
  const row=page.getByRole('row').filter({hasText:locale==='ar'?ai.label_ar:ai.label_en});
  await row.getByRole('spinbutton').fill('702');
  const update=page.waitForResponse(r=>r.url().endsWith(`/plans/${key}/features`)&&r.request().method()==='PATCH');
  await row.getByRole('button',{name:t('common.save'),exact:true}).click();
  assert.equal((await update).status(),200);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),true);
  await page.screenshot({path:process.env.SCREENSHOT_PATH.replace('.png','-features.png'),fullPage:true});
  const listed=await (await context.request.get(process.env.API_URL+'/platform/billing/standard-plans')).json();
  const plan=listed.plans.find(p=>p.plan_key===key);
  assert.equal(plan.is_active,false);
  assert.equal(plan.feature_limits.length,13);assert.equal(plan.entitlements.length,6);
  assert.equal(plan.feature_limits.find(f=>f.feature_code==='ai_credits').limit_value,702);
  assert.equal(plan.feature_limits.find(f=>f.feature_code==='data_credits').limit_value,1111);
  assert.equal(plan.monthly_price,87.21);assert.equal(plan.stripe_setup_required,true);
  await nav.getByRole('link',{name:t('billing.catalog.tabs.plans'),exact:true}).click();
  const planRow=page.getByRole('row').filter({hasText:key});
  await planRow.getByText(t('billing.catalog.plans.configurationStates.READY_TO_ACTIVATE'),{exact:true}).waitFor();
  await planRow.getByRole('button',{name:t('common.edit'),exact:true}).click();
  await dialog.waitFor();
  assert.equal(await dialog.getByLabel(t('billing.catalog.plans.planKey'),{exact:true}).getAttribute('readonly'),'');
  await dialog.getByLabel(t('billing.catalog.fields.name'),{exact:true}).fill(key+' edited');
  await dialog.getByLabel(t('billing.catalog.plans.monthlyPriceUsd'),{exact:true}).fill('90.00');
  await dialog.getByLabel(t('billing.catalog.plans.auditReason'),{exact:true}).fill('Synthetic explicit draft term change');
  const draftUpdate=page.waitForResponse(r=>r.url().endsWith(`/plans/${key}/draft-terms`)&&r.request().method()==='PATCH');
  await dialog.getByRole('button',{name:t('common.save'),exact:true}).click();
  assert.equal((await draftUpdate).status(),200);
  await dialog.waitFor({state:'hidden'});
  const updated=(await (await context.request.get(process.env.API_URL+'/platform/billing/standard-plans')).json()).plans.find(p=>p.plan_key===key);
  assert.equal(updated.display_name,key+' edited');assert.equal(updated.monthly_price,90);
  assert.equal(updated.feature_limits.find(f=>f.feature_code==='ai_credits').limit_value,702);
  assert.equal(updated.is_active,false);assert.equal(updated.stripe_setup_required,true);
  await page.screenshot({path:process.env.SCREENSHOT_PATH,fullPage:true});
  assert.deepEqual(issues,[]);
  console.log('PASS real template creation, all features, grouped EN/AR allowances, owner edits, inactive/Stripe readiness; no checkout');
}finally{await browser.close();}

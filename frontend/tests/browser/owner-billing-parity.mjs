// Source-backed visual fixtures only. Run real owner-billing-original.mjs separately.
import {createServer} from 'vite';
import {chromium} from 'playwright-core';
import {readFileSync,writeFileSync,existsSync,mkdirSync,unlinkSync,readdirSync} from 'node:fs';
import {resolve,join} from 'node:path';
const legacy=process.env.KEEL_ORIGINAL_FRONTEND,out=process.env.E2E_OUTPUT;
if(!legacy||!out)throw new Error('Explicit read-only legacy source/evidence paths required');
mkdirSync(out,{recursive:true});const files=[],results=[],consoleIssues=[];let server,browser;
function copy(target,source){target=resolve(target);if(existsSync(target))throw new Error('Refuse to overwrite '+target);writeFileSync(target,source);files.push(target);}
try{
 const ui=readdirSync(join(legacy,'src/shared/components/ui')).filter(n=>n.endsWith('.jsx'));
 for(const name of ui){let s=readFileSync(join(legacy,'src/shared/components/ui',name),'utf8');for(const n of ui)s=s.replaceAll('./'+n,'./.reference-'+n);copy('src/shared/components/ui/.reference-'+name,s);}
 for(const [folder,name] of [['pages','BillingCatalogPage'],['components','CustomPlanQuoteManager'],['components','InfrastructureRateCards']]){
  let s=readFileSync(join(legacy,'src/features/billing',folder,name+'.jsx'),'utf8');
  s=s.replaceAll('"swr"','"../../../shared/lib/useSWRCompat.js"');
  s=s.replace(/import \{\s*billingApi,\s*getApiError,\s*isForbiddenBillingError,?\s*\} from "..\/api\/billingApi.js";/g,'import {billingApi} from "../api/billingApi.js"; import {getApiError,isForbiddenBillingError} from "../api/catalogPresentationErrors.js";');
  s=s.replace('import { getApiError } from "../api/billingApi.js";','import {getApiError} from "../api/catalogPresentationErrors.js";');
  for(const n of ui)s=s.replaceAll('shared/components/ui/'+n,'shared/components/ui/.reference-'+n);
  s=s.replaceAll('components/CustomPlanQuoteManager.jsx','components/.reference-CustomPlanQuoteManager.jsx').replaceAll('./InfrastructureRateCards.jsx','./.reference-InfrastructureRateCards.jsx');
  s=s.replaceAll('../styles/Billing.css','../styles/.reference-Billing.css').replaceAll('../styles/PlansSubscription.css','../styles/.reference-PlansSubscription.css');
  copy('src/features/billing/'+folder+'/.reference-'+name+'.jsx',s);
 }
 for(const n of ['Billing','PlansSubscription'])copy('src/features/billing/styles/.reference-'+n+'.css',readFileSync(join(legacy,'src/features/billing/styles',n+'.css'),'utf8'));
 copy('src/styles/.reference-globals.css',readFileSync(join(legacy,'src/styles/globals.css'),'utf8'));
 copy('src/.owner-billing-parity.jsx',`import React from 'react';import {createRoot} from 'react-dom/client';import {MemoryRouter} from 'react-router-dom';import {QueryClient,QueryClientProvider} from '@tanstack/react-query';import {I18nProvider} from './app/providers/I18nProvider.jsx';
 const p=new URLSearchParams(location.search),reference=p.get('variant')==='reference',tab=p.get('tab')||'plans';
 if(reference)await import('./styles/.reference-globals.css');else{await import('./styles/globals.css');await import('./styles/apex-theme.css');await import('./styles/apex-components.css');await import('./styles/apex-motion.css');await import('./styles/keel-glass.css');}
 await import('./features/platform-admin/styles/PlatformAdmin.css');
 const {BillingCatalogPage}=await import(reference?'./features/billing/pages/.reference-BillingCatalogPage.jsx':'./features/billing/pages/BillingCatalogPage.jsx');
 const plan={id:'growth',name:'Synthetic Growth',name_ar:'نمو تجريبي',basePrice:'55.00',currency:'USD',isActive:true,trialPeriodValue:14,tier_level:2,pricingOptions:[{period:'monthly',intervalUnit:'month',intervalCount:1,discountPercent:0,totalPrice:55}]};
 const features=[{id:'connected_data_sources',code:'connected_data_sources',name:'Connected data sources',name_ar:'مصادر البيانات',type:'limit',unit:'sources',aggregationType:'max',resetCycle:'lifetime'}];
 const quote={id:'q-synthetic',name:'Synthetic quote',nameAr:'عرض تجريبي',tenantId:'t-synthetic',tenant:{businessName:'SYNTHETIC tenant'},status:'calculated',currency:'USD',estimatedTotalCost:'10',minimumSafePrice:'13.33',recommendedPrice:'13.34',pricingAvailable:true,quoteFeatures:[{featureId:'connected_data_sources',limitValue:10,estimatedUsage:10}],pricingInputs:{monthlyInfrastructureCost:0,activePayingTenants:1},targetGrossMargin:.25,maxVendorCostRevenueRatio:.2};
 const policy={currency:'USD',targetGrossMargin:.25,fixedPlatformFee:0,monthlyInfrastructureCost:0,activePayingTenants:1,estimatedOtherCost:0,roundingIncrement:.01,maxAutomaticMonthlyPrice:2500,maxAutomaticQuotaPerFeature:500000,enforceVendorCostRatioFloor:false,maxVendorCostRevenueRatio:.2,featureLimits:{},monitoringCadences:[{minutes:1440,code:'daily'}]};
 const empty=p.get('state')==='empty',wrap=data=>p.get('state')==='loading'?new Promise(()=>{}):p.get('state')==='error'?Promise.reject(new Error('SYNTHETIC presentation failure')):Promise.resolve({data});
 const api={capabilities:reference?undefined:{planTerms:false,featureDefinitions:false,customContractToggle:false},getPlans:()=>wrap(empty?[]:[plan]),getFeatures:()=>wrap(empty?[]:features),getPromoCodes:()=>wrap(empty?[]:[{id:'promo-fixture',code:'SYNTHETIC',discountType:'percentage',discountValue:10,maxUses:3,maxUsesPerUser:1,usedCount:0,isActive:false,status:'draft'}]),getCustomPlanQuotes:()=>wrap(empty?[]:[quote]),getVendorRates:()=>wrap([]),getInfrastructureRates:()=>wrap([]),getCustomPlans:()=>wrap([]),getSubscriptions:()=>wrap([]),getTenants:()=>wrap([{id:'t-synthetic',businessName:'SYNTHETIC tenant'}]),getPlanFeatures:()=>wrap([{feature_id:'connected_data_sources',limit_value:10,feature:features[0]}]),getCustomPlanPricingPolicy:()=>wrap(reference?policy:{...policy,versioned:true,policies:[]})};
 const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
 createRoot(document.getElementById('root')).render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin/billing?tab='+tab]}><I18nProvider><main className="pa-shell" style={{padding:'24px'}}><BillingCatalogPage api={api} platformMode canManage canManagePricing/></main></I18nProvider></MemoryRouter></QueryClientProvider>);`);
 server=await createServer({cacheDir:join(out,'vite-cache'),server:{host:'127.0.0.1',port:0},plugins:[{name:'owner-parity',configureServer(s){s.middlewares.use((req,res,next)=>{if(!req.url.startsWith('/__owner_parity'))return next();res.setHeader('Content-Type','text/html');res.end('<!doctype html><html><head><meta charset="utf-8"><script type="module">import RefreshRuntime from "/@react-refresh";RefreshRuntime.injectIntoGlobalHook(window);window.$RefreshReg$=()=>{};window.$RefreshSig$=()=>t=>t;window.__vite_plugin_react_preamble_installed__=true;</script><style>*,*::before,*::after{animation:none!important;transition:none!important}body{margin:0}</style></head><body><div id="root"></div><script type="module" src="/src/.owner-billing-parity.jsx"></script></body></html>');});}}]});
 await server.listen();const base='http://127.0.0.1:'+server.httpServer.address().port;
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
 for(const locale of ['en','ar'])for(const width of [1440,390])for(const theme of ['light','dark']){
  const context=await browser.newContext({viewport:{width,height:1000},deviceScaleFactor:1});await context.addInitScript(({locale,theme})=>{localStorage.setItem('ceopro_locale',locale);document.addEventListener('DOMContentLoaded',()=>{if(theme==='dark')document.documentElement.dataset.theme='dark';});},{locale,theme});const page=await context.newPage();let activeCase={};page.on('console',m=>{if(m.type()==='error')consoleIssues.push({...activeCase,message:m.text()});});
  const cases=['plans','custom-plans','custom-quotes','promos','features','plan-features','subscriptions'].map(tab=>({tab,state:'page'}));
  if(theme==='light')cases.push({tab:'plans',state:'empty'},{tab:'plans',state:'loading'},{tab:'plans',state:'error'},
    {tab:'plans',state:'create-plan'},{tab:'promos',state:'create-promotion'},{tab:'features',state:'edit-feature'},
    {tab:'custom-quotes',state:'create-quote'},{tab:'custom-quotes',state:'create-vendor'});
  const messages=JSON.parse(readFileSync('src/assets/locales/'+locale+'.json','utf8'));
  const t=k=>k.split('.').reduce((v,p)=>v?.[p],messages)||k;
  const selected=process.env.KEEL_PARITY_STATE?cases.filter(c=>c.state===process.env.KEEL_PARITY_STATE):cases;
  for(const {tab,state} of selected){
   const pair=[],measure=[];
   for(const variant of ['reference','current']){
    activeCase={variant,tab,state,locale,width,theme};await page.mouse.move(0,0);
    await page.goto(base+'/__owner_parity?variant='+variant+'&tab='+tab+'&state='+state);await page.locator('.billing-catalog-page').waitFor();await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(200);
    const actions={'create-plan':'billing.catalog.plans.create','create-promotion':'billing.catalog.promos.create','edit-feature':'common.edit','create-quote':'billing.catalog.customPlans.create','create-vendor':'billing.catalog.customPlans.vendorRates.create'};
    if(actions[state]){await page.getByRole('button',{name:t(actions[state]),exact:true}).first().click();await page.getByRole('dialog').waitFor();await page.waitForTimeout(150);}
    if(state==='create-promotion'){
      const dialog=page.getByRole('dialog');
      await dialog.getByLabel(t('billing.catalog.fields.status'),{exact:true}).selectOption('false');
      await dialog.getByLabel(t('billing.catalog.fields.startsAt'),{exact:true}).fill('2026-10-28T09:00');
      await dialog.getByLabel(t('billing.catalog.fields.expiresAt'),{exact:true}).fill('2026-11-28T09:00');
    }
    pair.push(await page.screenshot({path:join(out,[tab,state,locale,width,theme,variant].join('-')+'.png'),fullPage:true}));
    measure.push(await page.locator('.billing-catalog-page').evaluate(e=>({width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height,font:getComputedStyle(e).fontFamily,color:getComputedStyle(e).color,buttons:[...e.querySelectorAll('button')].slice(0,3).map(b=>({radius:getComputedStyle(b).borderRadius,background:getComputedStyle(b).backgroundColor,font:getComputedStyle(b).fontFamily}))})));
   }
   results.push({tab,state,locale,width,theme,exactScreenshotMatch:pair[0].equals(pair[1]),measurements:{reference:measure[0],current:measure[1]},fixture:'SYNTHETIC PRESENTATION ONLY'});
  }await context.close();
 }
 if(!results.length)throw new Error('No visual case matched the requested state');
}catch(e){writeFileSync(join(out,'failure.txt'),e.stack);throw e;}finally{if(browser)await browser.close();if(server)await server.close();for(const f of files)unlinkSync(f);writeFileSync(join(out,'visual-results.json'),JSON.stringify(results,null,2));writeFileSync(join(out,'visual-console.json'),JSON.stringify(consoleIssues,null,2));}
console.log('Compared '+results.length+' matched states; exact screenshot matches='+results.filter(r=>r.exactScreenshotMatch).length+'. Review differences before claiming visual parity.');

// Controlled original-source component comparison; synthetic presentation fixtures only.
import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {MemoryRouter} from 'react-router-dom';import {QueryClient,QueryClientProvider} from '@tanstack/react-query';import {createServer} from 'vite';import {chromium} from 'playwright-core';
import {readFileSync,writeFileSync,mkdirSync,existsSync,unlinkSync} from 'node:fs';import {join,resolve} from 'node:path';
const original=process.env.KEEL_ORIGINAL_FRONTEND,out=process.env.E2E_EVIDENCE_DIR;if(!original||!out)throw Error('Explicit original and evidence paths required');mkdirSync(out,{recursive:true});
const root=resolve('src'),entries=[['onboarding/components','OnboardingPageShell'],['onboarding/components','OnboardingActions'],['onboarding/components','IndustryPicker'],['onboarding/components','BusinessSizeForm'],['onboarding/components','GoalsMultiSelect'],['onboarding/pages','OnboardingRegionalPreferencesPage'],['onboarding/pages','OnboardingIndustryPage'],['onboarding/pages','OnboardingBusinessSizePage'],['onboarding/pages','OnboardingGoalsPage'],['billing/components','PlanSelector'],['billing/components','PlanSummaryCard'],['billing/components','SubscriptionResult']];
const created=[],results=[];let vite,browser;
function cleanupReference(file){if(!file.startsWith(root))throw Error('Unsafe cleanup path');unlinkSync(file);}
try{
 for(const [folder,name] of entries){let source=readFileSync(join(original,'src/features',folder,name+'.jsx'),'utf8');for(const [,dep] of entries)source=source.replaceAll(dep+'.jsx','.original-onboarding-'+dep+'.jsx');if(name==='PlanSelector')source=source.replace('"./PlanCard.jsx"','"./OriginalPlanCard.jsx"');const target=join(root,'features',folder,'.original-onboarding-'+name+'.jsx');if(existsSync(target))throw Error('Existing reference file protected');writeFileSync(target,source);created.push(target);}
 vite=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'silent'});
 const {I18nProvider}=await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');const {useOnboardingStore}=await vite.ssrLoadModule('/src/features/onboarding/store/onboardingStore.js');
 useOnboardingStore.getState().hydrate({country:'JO',city:'amman',industry:'retail',businessSize:'1-50',annualRevenue:'under-100k',objectives:['forecasting'],revision:4,highestCompletedStep:4});
 const cases=[['OnboardingRegionalPreferencesPage',{}],['OnboardingIndustryPage',{}],['OnboardingBusinessSizePage',{}],['OnboardingGoalsPage',{}],['PlanSelector',{plans:[{id:'growth',name:'Growth',name_ar:'النمو',isActive:true,tier_level:2,basePrice:140,pricingOptions:[{period:'monthly',totalPrice:140,currency:'USD',intervalCount:1,intervalUnit:'month'}],features:{tracked_products:{type:'limit',name:'Products',name_ar:'المنتجات',limitValue:250,unit:'products'}}}],selectedPlan:'growth',billingPeriod:'monthly',onPlanSelect:()=>{},onPeriodChange:()=>{}}],['PlanSummaryCard',{plan:{id:'starter',name:'Starter',name_ar:'البداية',basePrice:55,currency:'USD',features:{},pricingOptions:[{period:'monthly',totalPrice:55,intervalCount:1,intervalUnit:'month'}]},billingPeriod:'monthly'}],['SubscriptionResult',{status:'confirmed',onPrimary:()=>{}}],['SubscriptionResult',{status:'pending',onRetry:()=>{}}]];
 const foundation=['globals','apex-theme','apex-components','apex-motion','keel-glass'].map(n=>`<link rel="stylesheet" href="http://127.0.0.1:5204/src/styles/${n}.css?direct">`).join('');
 const sheets=['onboarding/styles/Onboarding.css','billing/styles/Billing.css','billing/styles/PlansSubscription.css','data-connections/styles/DataConnections.css'];
 browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
 for(const locale of ['en','ar'])for(const width of [1440,390]){
  const context=await browser.newContext({viewport:{width,height:1050}}),page=await context.newPage();
  for(let index=0;index<cases.length;index++){
   const [name,props]=cases[index],folder=entries.find(e=>e[1]===name)[0],pictures=[];
   for(const variant of ['original','integrated']){
    const file=variant==='original'?'.original-onboarding-'+name:name==='PlanSelector'?'OriginalPlanSelector':name;
    const mod=await vite.ssrLoadModule('/src/features/'+folder+'/'+file+'.jsx'),Component=mod[name]||mod.OriginalPlanSelector;
    const previous=globalThis.window;globalThis.window={localStorage:{getItem:()=>locale}};let html;
    try{html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client:new QueryClient()},React.createElement(MemoryRouter,null,React.createElement(I18nProvider,null,React.createElement(Component,props)))));}finally{if(previous===undefined)delete globalThis.window;else globalThis.window=previous;}
    const css=variant==='original'?'<style>'+sheets.map(path=>readFileSync(join(original,'src/features',path),'utf8')).join('\n')+'</style>':sheets.map(path=>`<link rel="stylesheet" href="http://127.0.0.1:5204/src/features/${path}?direct">`).join('');
    const content=`<!doctype html><html lang="${locale}" dir="${locale==='ar'?'rtl':'ltr'}"><head><base href="http://127.0.0.1:5204/">${foundation}${css}<style>body{margin:0;padding:24px}main{max-width:1100px;margin:auto}*,*::before,*::after{animation:none!important;transition:none!important}</style></head><body><main>${html}</main></body></html>`;
    await page.setContent(content,{waitUntil:'networkidle'});await page.evaluate(async()=>{await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});await page.waitForTimeout(150);pictures.push(await page.screenshot({path:join(out,`${index}-${name}-${locale}-${width}-${variant}.png`),fullPage:true}));
   }
   results.push({component:name,case:index,locale,width,exactScreenshotMatch:pictures[0].equals(pictures[1]),scope:'SYNTHETIC_CONTROLLED_COMPONENT_ONLY',reference:join(original,'src/features',folder,name+'.jsx')});
  }await context.close();
 }
}finally{if(browser)await browser.close();if(vite)await vite.close();for(const file of created)cleanupReference(file);writeFileSync(join(out,'visual-comparison.json'),JSON.stringify(results,null,2));}
console.log(`Compared ${results.length} original/integrated onboarding component cases; exact matches=${results.filter(r=>r.exactScreenshotMatch).length}. Full-app parity is a separate claim.`);

// Source-backed component visual comparison, using labeled synthetic fixtures only.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createServer } from 'vite';
import { chromium } from 'playwright-core';
import { readFileSync, writeFileSync, existsSync, mkdirSync, unlinkSync } from 'node:fs';
import { resolve, join } from 'node:path';

const original=process.env.KEEL_ORIGINAL_FRONTEND;
const evidence=process.env.E2E_EVIDENCE_DIR;
if(!original||!evidence)throw new Error('Explicit original read-only source and evidence paths required');
mkdirSync(evidence,{recursive:true});
const components=resolve('src/features/billing/components');
const names=['PlanCard','CurrentPlanCard','UsageLimitGrid','PlanComparisonTable','InvoiceHistoryTable','InvoiceDownloadButton','CustomPlanBuilder','CustomPlanQuantityField','CustomPlanCallout','UpgradeRecommendation'];
const created=[];
let vite,browser;
const results=[];
try {
  for(const name of names) {
    let source=readFileSync(join(original,'src/features/billing/components',name+'.jsx'),'utf8');
    for(const dependency of names)source=source.replaceAll(`"./${dependency}.jsx"`,`"./.original-ui-reference-${dependency}.jsx"`).replaceAll(`'./${dependency}.jsx'`,`'./.original-ui-reference-${dependency}.jsx'`);
    const target=join(components,`.original-ui-reference-${name}.jsx`);
    if(existsSync(target))throw new Error('Refuse to overwrite an existing reference file');
    writeFileSync(target,source);created.push(target);
  }
  vite=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'silent'});
  const {I18nProvider}=await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
  const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH,headless:true,chromiumSandbox:true});
  const styles=['globals','apex-theme','apex-components','apex-motion','keel-glass'];
  const baseCss=styles.map(name=>`<link rel="stylesheet" href="http://127.0.0.1:5204/src/styles/${name}.css?direct">`).join('');
  const originalCss=['Billing','PlansSubscription'].map(name=>readFileSync(join(original,'src/features/billing/styles',name+'.css'),'utf8')).join('\n');
  const currentCss=['Billing','PlansSubscription','CustomPlan'].map(name=>`<link rel="stylesheet" href="http://127.0.0.1:5204/src/features/billing/styles/${name}.css?direct">`).join('');
  for(const locale of ['en','ar']) {
    const t=(key,values)=>translate(locale,key,values);
    const plan={id:'growth',name:'Growth',name_ar:'النمو',featured:true,isActive:true,tier_level:2,basePrice:140,
      pricingOptions:[{period:'monthly',totalPrice:140,currency:'USD',intervalUnit:'month',intervalCount:1}],
      features:{tracked_products:{type:'limit',name:'Product capacity',name_ar:'سعة المنتجات',limitValue:250,unit:'products'},market_intelligence:{type:'boolean',name:'Market intelligence',name_ar:'معلومات السوق'}}};
    const props={
      PlanCard:{plan,billingPeriod:'monthly',onSelect:()=>{},actionLabel:t('billing.management.currentPlan'),actionDisabled:true},
      CurrentPlanCard:{plan,locale,t,subscription:{status:'active',billingPeriod:'monthly',currentPeriodEnd:'2026-11-25T12:00:00Z'},currentSubscription:{status:'active',billingPeriod:'monthly'},formatDate:()=> '2026-11-25'},
      UsageLimitGrid:{locale,t,features:plan.features,usage:{tracked_products:100,market_intelligence:true},limits:{tracked_products:250,market_intelligence:true}},
      PlanComparisonTable:{plans:[plan,{id:'custom',name:t('billing.plans.custom.name'),isCustomBuilder:true,features:{}}],currentPlanId:'growth'},
      InvoiceHistoryTable:{locale,t,invoices:[]},
      CustomPlanBuilder:{features:[{id:'data_credits',code:'data_credits',type:'limit',name:'Data Credits',name_ar:'رصيد البيانات',unit:'credits',min:0,max:100}],configuration:{data_credits:{selected:true,limitValue:20}},onChange:()=>{}},
      CustomPlanCallout:{onSelect:()=>{}},
      UpgradeRecommendation:{t,recommendation:{titleKey:'billing.management.upgradeRecommendationTitle',descriptionKey:'billing.management.upgradeRecommendationDescription'},onCompare:()=>{}},
    };
    for(const width of [1440,390]) {
      const context=await browser.newContext({viewport:{width,height:1000}});
      const page=await context.newPage();
      for(const [name,componentProps] of Object.entries(props)) {
        const pictures=[];
        for(const variant of ['original','integrated']) {
          const file=variant==='original'?`.original-ui-reference-${name}.jsx`:name==='PlanCard'?'OriginalPlanCard.jsx':name+'.jsx';
          const Component=(await vite.ssrLoadModule('/src/features/billing/components/'+file))[name];
          const previous=globalThis.window;
          globalThis.window={localStorage:{getItem:()=>locale}};
          let markup;
          try {markup=renderToStaticMarkup(React.createElement(QueryClientProvider,{client:new QueryClient()},React.createElement(MemoryRouter,null,React.createElement(I18nProvider,null,React.createElement(Component,componentProps)))));}
          finally {if(previous===undefined)delete globalThis.window;else globalThis.window=previous;}
          const css=variant==='original'?`<style>${originalCss}</style>`:currentCss;
          const html=`<!doctype html><html lang="${locale}" dir="${locale==='ar'?'rtl':'ltr'}"><head><meta charset="utf-8">${baseCss}${css}<style>body{margin:0;padding:24px}main{max-width:1100px;margin:auto}*,*::before,*::after{animation:none!important;transition:none!important}</style></head><body><main>${markup}</main></body></html>`;
          const stem=`${name}-${locale}-${width}-${variant}`;
          writeFileSync(join(evidence,stem+'.html'),html);
          await page.setContent(html,{waitUntil:'networkidle'});
          await page.evaluate(()=>document.fonts.ready);
          const picture=await page.screenshot({path:join(evidence,stem+'.png'),fullPage:true});
          pictures.push(picture);
        }
        results.push({component:name,locale,width,exactScreenshotMatch:pictures[0].equals(pictures[1]),fixture:'SYNTHETIC_PRESENTATION_ONLY',reference:join(original,'src/features/billing/components',name+'.jsx')});
      }
      await context.close();
    }
  }
} finally {
  if(browser)await browser.close();
  if(vite)await vite.close();
  for(const file of created)unlinkSync(file);
  writeFileSync(join(evidence,'visual-comparison.json'),JSON.stringify(results,null,2));
}
console.log(`Compared ${results.length} original/integrated component screenshots; exact matches=${results.filter(item=>item.exactScreenshotMatch).length}. Review recorded differences before claiming parity.`);

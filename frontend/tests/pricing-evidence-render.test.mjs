import test from 'node:test';import assert from 'node:assert/strict';import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';import {readFileSync} from 'node:fs';
import {PricingEvidenceDetails} from '../src/features/market-intelligence/components/PricingEvidenceDetails.jsx';
globalThis.React=React;
for(const locale of ['en','ar'])test(`${locale}: real evidence rendering labels converted references separately and escapes source content`,()=>{
 const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`,import.meta.url)));
 const t=(key,args={})=>Object.entries(args).reduce((s,[k,v])=>s.replaceAll('{{'+k+'}}',String(v)),key.split('.').reduce((v,k)=>v?.[k],messages));
 const html=renderToStaticMarkup(React.createElement(PricingEvidenceDetails,{t,localize:value=>value?.[locale],formatDate:v=>v,money:(n,c)=>`${n} ${c}`,
  recommendation:{status:'OK',confidence_score:0.35,generated_at:'2026-10-15',sources:[{competitor_price_id:'local',competitor_name:'Local market',original_price:8,original_currency:'JOD',observed_at:'2026-10-14'}],
   reference_sources:[{competitor_price_id:'reference',competitor_name:'<img src=x onerror=alert(1)>',original_price:10,original_currency:'USD',converted_price:7.1,currency:'JOD',observed_at:'2026-10-14',conversion:{rate:0.71,as_of:'2026-10-15',source:'fixture bank'}}]}}));
 assert.ok(html.includes(t('marketMain.pricingFix.referenceOnly')));assert.ok(html.includes('8 JOD'));assert.ok(html.includes('7.1 JOD'));assert.ok(html.includes('fixture bank'));
 assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));assert.ok(!html.includes('overflow'));
});

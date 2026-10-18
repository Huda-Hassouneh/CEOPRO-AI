import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {readFileSync} from 'node:fs';
import {PricingRecommendationContent} from '../src/features/market-intelligence/components/PricingRecommendationContent.jsx';
globalThis.React=React;
for(const locale of ['en','ar']){
 const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`,import.meta.url)));
 const t=(key,args={})=>{const value=key.split('.').reduce((v,k)=>v?.[k],messages);assert.equal(typeof value,'string',`Missing ${locale}:${key}`);return Object.entries(args).reduce((s,[k,v])=>s.replaceAll('{{'+k+'}}',String(v)),value);};
 const saved={request_id:'saved',status:'OK',generated_at:'2026-10-18',currency:'JOD',suggested_price:9,explanation_i18n:{en:'Supported by confirmed prices.',ar:'تستند إلى أسعار معتمدة.'}};
 const row={action:'lower',currentPrice:10,suggestedPrice:9,currency:'JOD',matchedCompetitors:2,marketAverage:9.4};
 const props={recommendation:null,row:null,productName:'<script>product</script>',savedRecommendations:[],credits:{remaining:3},t,localize:v=>v?.[locale],money:(n,c)=>n==null?'—':`${n} ${c}`,number:String,formatDate:String,onSelect(){},onReloadHistory(){},onDismissError(){}};
 const render=overrides=>renderToStaticMarkup(React.createElement(PricingRecommendationContent,{...props,...overrides}));
 test(`${locale}: result distinguishes real prices, explanation and action without inventing confidence`,()=>{
  const html=render({recommendation:saved,row,savedRecommendations:[saved]});
  assert.ok(html.includes('10 JOD'));assert.ok(html.includes('9 JOD'));assert.ok(html.includes(t('marketMain.pricingUx.actions.lower')));
  assert.ok(html.includes(saved.explanation_i18n[locale]));assert.ok(!html.includes('0%'));assert.ok(!html.includes('<table'));assert.ok(!html.includes('<select'));
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
 });
 test(`${locale}: unavailable result never reveals unsafe suggestion or action`,()=>{
  const html=render({recommendation:{...saved,status:'UNKNOWN',suggested_price:9999},row:{...row,suggestedPrice:9999}});
  assert.ok(html.includes(t('marketMain.pricingUx.unavailableTitle')));assert.ok(!html.includes('9999'));assert.ok(!html.includes(t('marketMain.pricingUx.actions.lower')));assert.ok(html.includes(t('marketMain.pricingUx.nextStep')));
 });
 test(`${locale}: initial market data, loading and durable errors stay distinct`,()=>{
  assert.ok(render({row}).includes('9.4 JOD'));assert.ok(render({row}).includes('10 JOD'));
  const loading=render({historyLoading:true});assert.ok(loading.includes('role="status"'));assert.ok(!loading.includes(t('marketMain.pricingUx.emptyTitle')));
  const error=render({errorMessage:'Network diagnostic',historyError:true});assert.ok(error.includes('role="alert"'));assert.ok(error.includes('Network diagnostic'));assert.ok(error.includes(t('marketMain.pricingFix.historyError')));assert.ok(error.includes(t('marketMain.pricingUx.dismiss')));
 });
 test(`${locale}: saved history is labelled, localised and locked while generating; stale price is clearly historical`,()=>{
  const html=render({recommendation:{...saved,is_stale:true},row,isGenerating:true,savedRecommendations:[saved,{...saved,request_id:'unknown',status:'UNKNOWN'}]});
  assert.match(html,/<label[^>]+for="[^"]+"/);assert.match(html,/<select[^>]+disabled/);assert.ok(!html.includes('UNKNOWN'));assert.ok(html.includes(t('marketMain.pricingUx.recordedPrice')));assert.ok(html.includes(t('marketMain.pricingFix.stale')));
 });
}

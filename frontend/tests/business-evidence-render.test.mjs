import test from 'node:test';import assert from 'node:assert/strict';import React from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {readFileSync} from 'node:fs';
import {RecommendationEvidence} from '../src/features/business-recommendations/RecommendationEvidence.jsx';globalThis.React=React;
for(const locale of ['en','ar'])test(locale+': recommendation evidence renders actual ledger, target day and escaped competitor text',()=>{
 const messages=JSON.parse(readFileSync(new URL('../src/assets/locales/'+locale+'.json',import.meta.url)));
 const t=(key,args={})=>Object.entries(args).reduce((s,[k,v])=>s.replaceAll('{{'+k+'}}',String(v)),key.split('.').reduce((v,k)=>v?.[k],messages)??key);
 const html=renderToStaticMarkup(React.createElement(RecommendationEvidence,{t,locale,evidence:{generated_at:'2026-10-15T12:00:00Z',sales:{source:'transactions',recent_units:30,prior_units:100,record_count:2},sources:[{table:'competitor_prices',competitor_name:'<img src=x onerror=alert(1)>',price:8,currency:'JOD',observed_at:'2026-10-14T12:00:00Z'},{table:'demand_forecasts',expected_units:4,target_date:'2026-10-21',prediction_kind:'target_day'}]}}));
 assert.ok(html.includes(new Intl.NumberFormat(locale).format(30)));assert.ok(html.includes(new Intl.NumberFormat(locale).format(100)));assert.ok(html.includes(new Intl.NumberFormat(locale).format(8)+' JOD'));assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));assert.ok(!html.includes('overflow'));
});

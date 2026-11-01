import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

let vite, EconomicReadiness, I18nProvider;
test.before(async()=>{
  vite=await createServer({server:{middlewareMode:true},appType:'custom',logLevel:'silent'});
  ({EconomicReadiness}=await vite.ssrLoadModule('/src/features/platform/EconomicReadiness.jsx'));
  ({I18nProvider}=await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx'));
});
test.after(async()=>{await vite.close();});

test('completeness distinguishes rates, credential presence, provenance and approvals without claiming health',()=>{
  const data={feature_economics:{rag_assistant:{feature_code:'rag_assistant',treatment:'ai_and_data_credits',source:'runtime source'}},
    provider_readiness:{catalog_version:'test-v1',approvals:[{setting:'PLACES_TERMS_APPROVAL_REFERENCE',present:false}],providers:[{
      provider:'groq',operation:'model',rates:[{unit:'input_token',status:'VERIFIED',provenance:'catalog/bootstrap'}],
      credential_status:'MISSING',missing_settings:['GROQ_API_KEY'],approval_requirements:[],
    }]}};
  for(const locale of ['en','ar']){
    const messages=JSON.parse(readFileSync(`src/assets/locales/${locale}.json`,'utf8')).billing.pricingStudio;
    const text=key=>key.split('.').reduce((o,k)=>o?.[k],messages) || key;
    const client=new QueryClient();
    const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(I18nProvider,null,React.createElement(EconomicReadiness,{data,text}))));
    client.clear();
    for(const value of ['groq / model','rag_assistant','GROQ_API_KEY','PLACES_TERMS_APPROVAL_REFERENCE',messages.catalog.MISSING,messages.catalog.operational,messages.catalog.origins['catalog/bootstrap']])assert.ok(html.includes(value),value);
    if(locale==='ar')for(const [key,value] of Object.entries(messages.catalog))if(typeof value==='string')assert.match(value,/[\u0600-\u06ff]/,key);
  }
});

test('older inputs do not fabricate setup evidence',()=>{
  assert.equal(renderToStaticMarkup(React.createElement(EconomicReadiness,{data:{},text:x=>x})), '');
});

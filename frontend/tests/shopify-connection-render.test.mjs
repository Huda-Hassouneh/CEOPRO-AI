import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {readFileSync} from 'node:fs';
import {ShopifyAuthorizationFields,storeErrorMessage} from '../src/features/data-connections/components/WebsiteStoreSetup.jsx';
globalThis.React=React;
for(const language of ['en','ar'])test(`${language}: Shopify authorization uses scoped consent, canonical domain and explicit test-order opt-in`,()=>{
 const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${language}.json`,import.meta.url)));
 const t=key=>key.split('.').reduce((v,k)=>v?.[k],messages);
 const noop=()=>{};
 const html=renderToStaticMarkup(React.createElement(ShopifyAuthorizationFields,{t,url:'',setUrl:noop,minutes:'60',setMinutes:noop,consent:false,setConsent:noop,includeTests:false,setIncludeTests:noop,busy:false}));
 assert.ok(html.includes('your-store.myshopify.com'));assert.equal((html.match(/type="checkbox"/g)||[]).length,2);assert.match(html,/type="checkbox" required/);assert.ok(!html.includes('type="password"'));assert.ok(!html.includes('undefined'));
 assert.ok(html.includes(t('storeConnection.shopify.history')));
 for(const code of ['STORE_INVALID_SHOPIFY_DOMAIN','STORE_SHOPIFY_AUTH_FAILED','STORE_SHOPIFY_AUTH_EXPIRED','STORE_RATE_LIMITED','STORE_PAYMENT_EVIDENCE_MISSING'])assert.equal(storeErrorMessage({response:{data:{code}}},t),t('storeConnection.errors.'+code));
});

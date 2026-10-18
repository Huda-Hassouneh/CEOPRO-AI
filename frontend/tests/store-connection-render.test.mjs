import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {readFileSync} from 'node:fs';
import {StoreAuthorizationFields,storeErrorMessage} from '../src/features/data-connections/components/WebsiteStoreSetup.jsx';
globalThis.React=React;
for(const language of ['en','ar'])test(`${language}: real store authorization fields require consent and explain import scope`,()=>{
 const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${language}.json`,import.meta.url)));
 const t=key=>key.split('.').reduce((v,k)=>v?.[k],messages);
 const html=renderToStaticMarkup(React.createElement(StoreAuthorizationFields,{t,keyValue:'',secret:'',minutes:'60',consent:false,busy:false,setKey:()=>{},setSecret:()=>{},setMinutes:()=>{},setConsent:()=>{}}));
 assert.equal((html.match(/type="password"/g)||[]).length,2);
 assert.ok(html.includes(t('storeConnection.consent')));assert.match(html,/type="checkbox" required/);
 assert.ok(html.includes(t('storeConnection.importScope')));assert.ok(!html.includes('undefined'));
 assert.equal(storeErrorMessage({response:{data:{code:'STORE_ACCESS_DENIED'}}},t),t('storeConnection.errors.STORE_ACCESS_DENIED'));
 assert.equal(storeErrorMessage({response:{data:{code:'unknown-code',message:'secret provider error'}}},t),t('storeConnection.errors.STORE_SERVICE_UNAVAILABLE'));
});

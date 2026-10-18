import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { getApiErrorMessage } from '../src/shared/lib/apiErrorCore.js';
const read=(path)=>readFileSync(new URL(`../${path}`,import.meta.url),'utf8');
test('catalog errors have customer-facing English and Arabic messages',()=>{
 for(const locale of ['en','ar']){
  const messages=JSON.parse(read(`src/assets/locales/${locale}.json`));
  const t=key=>key.split('.').reduce((value,part)=>value?.[part],messages);
  for(const code of ['PRODUCT_CAPACITY_EXCEEDED','PRODUCT_DUPLICATE','PRODUCT_STALE_EDIT','PRODUCT_ARCHIVED'])
   assert.equal(getApiErrorMessage({code,message:'unlocalized backend message'},t),messages.apiErrors[code]);
  for(const reason of ['MISSING_INVENTORY','DUPLICATE_WAREHOUSE','INVALID_STOCK_DATE','STALE_INVENTORY','UNDATED_INVENTORY','INVALID_INVENTORY']) assert.ok(messages.catalog.stockReasons[reason]);
  assert.match(messages.catalog.capacity,/\{\{used\}\}/);
 }
});
test('catalog HTTP paths are real and Quick Sale cannot report local success',()=>{
 const api=read('src/features/products/api/productsApi.js');
 for(const method of ['get','post','patch','delete']) assert.ok(api.includes(`httpClient.${method}(`));
 assert.match(api,/expectedVersion/);assert.doesNotMatch(api,/ok:\s*true|products:\s*\[\]/);
 assert.match(read('src/features/products/api/quickSaleApi.js'),/NOT_IMPLEMENTED/);
 const page=read('src/features/products/pages/CatalogProductPage.jsx');
 assert.match(page,/setEditing\(product\)/);assert.match(page,/product=\{editing\}/);
 assert.match(page,/<Button disabled>\{t\('catalog.quickSale'\)\}/);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {validGtin,gtinKey} from '../src/features/products/utils/gtin.js';
test('browser GTIN validation preserves identifiers and distinguishes invalid checksums',()=>{
 assert.equal(validGtin('036000291452'),true);assert.equal(validGtin('036000291453'),false);
 assert.equal(validGtin('00000000'),false);assert.equal(gtinKey('036000291452'),'00036000291452');
});
test('actual GTIN form and import controls render in English and Arabic with text inputs',async()=>{
 const vite=await createServer({server:{middlewareMode:true},appType:'custom'});
 try{
  const {ProductForm}=await vite.ssrLoadModule('/src/features/products/components/ProductForm.jsx');
  const {GtinImport}=await vite.ssrLoadModule('/src/features/products/components/GtinImport.jsx');
  const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  for(const locale of ['en','ar']){
   const t=(key,values)=>translate(locale,key,values);
   const form=renderToStaticMarkup(React.createElement(ProductForm,{t,product:{gtin:'036000291452'},currencies:['JOD'],onSubmit:()=>{},onCancel:()=>{}}));
   assert.match(form,/type="text" inputMode="numeric"/);assert.match(form,/value="036000291452"/);assert.match(form,/maxLength="14"/);
   assert.ok(form.includes(locale==='en'?'GTIN / Barcode':'رقم GTIN'));assert.doesNotMatch(form,/catalog\.gtin|catalog\.fields\.gtin/);
   const empty=renderToStaticMarkup(React.createElement(ProductForm,{t,currencies:['JOD'],onSubmit:()=>{},onCancel:()=>{}}));assert.doesNotMatch(empty,/value="036000291452"/);
   const client=new QueryClient();const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(GtinImport,{t,locale})));client.clear();
   assert.match(html,/accept=".csv,.xlsx"/);assert.match(html,/product-gtin-template.csv/);assert.doesNotMatch(html,/catalog\.gtin/);
   assert.ok(html.includes(locale==='en'?'Preview GTIN changes':'معاينة تغييرات GTIN'));
   assert.ok(!html.includes(locale==='en'?'Save GTIN changes':'حفظ تغييرات GTIN'),'cannot apply before preview');
  }
 }finally{await vite.close();}
});

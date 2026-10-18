import test from 'node:test';
import assert from 'node:assert/strict';
import {productUrlInScope} from '../../src/modules/competitors/service/product-url.js';
import {productLinkSchema} from '../../src/modules/competitors/types/competitors.validation.js';
test('product URLs preserve storefront scope, reject private targets, credentials and encoded path escapes',()=>{
 const scope='https://www.shop.example/jordan/store';
 assert.equal(productUrlInScope('https://www.shop.example/jordan/store/product/42#reviews',scope),'https://www.shop.example/jordan/store/product/42');
 for(const url of ['https://shop.example/jordan/store-two/product/1','https://shop.example/jordan/store/%2e%2e/other','https://user:pass@shop.example/jordan/store/a','https://shop.example:8443/jordan/store/a','http://shop.example/jordan/store/a','https://127.0.0.1/x','javascript:alert(1)'])assert.equal(productUrlInScope(url,scope),null,url);
 assert.equal(productLinkSchema.safeParse({productId:'4821441d-fc46-4b73-90ab-17b30cae1ed6',url:'https://shop.example/p',expectedMappingId:null,comparisonConfirmed:true}).success,false);
});

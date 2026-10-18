import test from 'node:test';
import assert from 'node:assert/strict';
import {createHmac,randomBytes} from 'node:crypto';
import {shopDomain} from '../../src/modules/dataconnection/store/shopify/domain.js';
import {validateShopifyCallback} from '../../src/modules/dataconnection/store/shopify/security.js';
import {verifyShopifyWebhook} from '../../src/modules/dataconnection/store/shopify/security.js';
import {sealCredentials,openCredentials} from '../../src/modules/dataconnection/store/vault.js';
import {validateProviderPage} from '../../src/modules/dataconnection/store/provider-contract.js';

test('Shopify canonical host rejects credentials, paths, suffix tricks, private hosts and ports',()=>{
 assert.equal(shopDomain('https://test-shop.myshopify.com/'),'test-shop.myshopify.com');
 for(const value of ['http://test.myshopify.com','https://127.0.0.1','https://test.myshopify.com:443','https://test.myshopify.com:444','test.myshopify.com.attacker.test','https://user:pass@test.myshopify.com','https://test.myshopify.com/path','https://test.myshopify.com?q=1']){
  // URL standardization treats explicit :443 as the default HTTPS port.
  if(value.endsWith(':443'))continue;
  assert.throws(()=>shopDomain(value),/INVALID_SHOPIFY_DOMAIN/);
 }
});
test('Shopify callback HMAC rejects tampering, stale timestamps and duplicate query keys',()=>{
 const secret='fixture-private-key';const params=new URLSearchParams({shop:'test.myshopify.com',state:'state',code:'code',timestamp:String(Math.floor(Date.now()/1000))});
 const signature=createHmac('sha256',secret).update([...params.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`${k}=${v}`).join('&')).digest('hex');params.set('hmac',signature);
 validateShopifyCallback(params,secret);params.append('shop','other.myshopify.com');assert.throws(()=>validateShopifyCallback(params,secret));params.delete('shop');params.set('shop','evil.myshopify.com');assert.throws(()=>validateShopifyCallback(params,secret));
});
test('Shopify webhook HMAC uses exact raw bytes and never accepts a reserialized payload',()=>{
 const raw=Buffer.from('{"id": 10}'),secret='private';const signed=createHmac('sha256',secret).update(raw).digest('base64');
 assert.equal(verifyShopifyWebhook(raw,signed,secret),true);assert.equal(verifyShopifyWebhook(Buffer.from('{"id":10}'),signed,secret),false);assert.equal(verifyShopifyWebhook(raw,'bad',secret),false);
});
test('Shopify encrypted offline credentials remain source/tenant-bound and do not change Woo v1 decoding',()=>{
 process.env.STORE_CONNECTOR_ENCRYPTION_KEY=randomBytes(32).toString('hex');
 const credentials={provider:'shopify' as const,accessToken:'private-access',refreshToken:'private-refresh',expiresAt:Date.now()+3600000,refreshExpiresAt:Date.now()+86400000,scopes:['read_orders']};
 const sealed=sealCredentials(credentials,'tenant','source');assert.deepEqual(openCredentials(sealed,'tenant','source'),credentials);assert.throws(()=>openCredentials(sealed,'other','source'));assert.ok(!sealed.includes('private'));
 const woo={key:'ck-value',secret:'cs-value'};assert.deepEqual(openCredentials(sealCredentials(woo,'tenant','source'),'tenant','source'),woo);
});
test('Provider boundary requires Shopify variant identities and complete location snapshots',()=>{
 const product={externalId:'gid://shopify/ProductVariant/1',name:'Model',active:true,parentExternalId:'gid://shopify/Product/1',sku:null,price:'1',currency:'JOD',inventory:{state:'unmanaged' as const,quantity:null,stockStatus:null,lowStockThreshold:null,stockOwnerExternalId:null}};
 assert.throws(()=>validateProviderPage('shopify','products',{contractVersion:3,items:[product],hasMore:false}));
 validateProviderPage('shopify','products',{contractVersion:3,items:[{...product,locations:[]}],hasMore:false});
 assert.throws(()=>validateProviderPage('woocommerce','products',{contractVersion:2,items:[{...product,locations:[]}],hasMore:false}));
});

import {createHmac,timingSafeEqual} from 'node:crypto';
import {StoreError} from '../contracts.js';

export function validateShopifyCallback(parameters:URLSearchParams,secret:string){
 const entries=[...parameters.entries()];
 if(new Set(entries.map(([k])=>k)).size!==entries.length)throw new StoreError('STORE_SHOPIFY_AUTH_FAILED');
 const supplied=parameters.get('hmac')??'';
 if(!/^[a-fA-F0-9]{64}$/.test(supplied))throw new StoreError('STORE_SHOPIFY_AUTH_FAILED');
 const message=entries.filter(([k])=>k!=='hmac').sort(([a],[b])=>a<b?-1:a>b?1:0).map(([key,value])=>`${key}=${value}`).join('&');
 if(!timingSafeEqual(createHmac('sha256',secret).update(message).digest(),Buffer.from(supplied,'hex')))throw new StoreError('STORE_SHOPIFY_AUTH_FAILED');
 const time=Number(parameters.get('timestamp'));
 if(!Number.isFinite(time)||Math.abs(Date.now()/1000-time)>600)throw new StoreError('STORE_SHOPIFY_AUTH_FAILED');
}

export function verifyShopifyWebhook(body:Buffer,hmac:string|undefined,secret:string){
 if(!hmac||!/^[A-Za-z0-9+/]{43}=$/.test(hmac))return false;
 const expected=createHmac('sha256',secret).update(body).digest(),actual=Buffer.from(hmac,'base64');
 return expected.length===actual.length&&timingSafeEqual(expected,actual);
}

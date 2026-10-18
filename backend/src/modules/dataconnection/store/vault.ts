import {createCipheriv,createDecipheriv,randomBytes} from 'node:crypto';
import {StoreError} from './contracts.js';
function master(){
 const value=process.env.STORE_CONNECTOR_ENCRYPTION_KEY||'';
 if(!/^[a-fA-F0-9]{64}$/.test(value))throw new StoreError('CONNECTOR_NOT_CONFIGURED',503);
 return Buffer.from(value,'hex');
}
export type ShopifyCredentials={provider:'shopify';includeTestOrders?:boolean;accessToken:string;refreshToken:string;expiresAt:number;refreshExpiresAt:number;scopes:string[]};
export type StoreCredentials={key:string;secret:string}|ShopifyCredentials;
export function sealCredentials(value:StoreCredentials,tenantId:string,sourceId:string){
 const iv=randomBytes(12),cipher=createCipheriv('aes-256-gcm',master(),iv);
 cipher.setAAD(Buffer.from(`store-v1:${tenantId}:${sourceId}`));
 const encrypted=Buffer.concat([cipher.update(JSON.stringify(value),'utf8'),cipher.final()]);
 return ['v1',iv.toString('hex'),cipher.getAuthTag().toString('hex'),encrypted.toString('base64')].join('.');
}
export function openCredentials(value:string,tenantId:string,sourceId:string):StoreCredentials{
 try{
  const [version,iv,tag,body]=value.split('.');if(version!=='v1')throw Error();
  const decipher=createDecipheriv('aes-256-gcm',master(),Buffer.from(iv!,'hex'));
  decipher.setAAD(Buffer.from(`store-v1:${tenantId}:${sourceId}`));decipher.setAuthTag(Buffer.from(tag!,'hex'));
  const result=JSON.parse(Buffer.concat([decipher.update(Buffer.from(body!,'base64')),decipher.final()]).toString('utf8'));
  if(result.provider==='shopify'){if(typeof result.accessToken!=='string'||typeof result.refreshToken!=='string'||!Number.isFinite(result.expiresAt)||!Number.isFinite(result.refreshExpiresAt)||!Array.isArray(result.scopes))throw Error();}
  else if(typeof result.key!=='string'||typeof result.secret!=='string')throw Error();return result;
 }catch{throw new StoreError('STORE_CREDENTIALS_UNAVAILABLE',503);}
}

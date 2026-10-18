import jwt from 'jsonwebtoken';
import {createHash} from 'node:crypto';
import {StoreError} from './contracts.js';
export async function storeProvider(tenantId:string,input:Record<string,unknown>):Promise<unknown>{
 const base=process.env.STORE_CONNECTOR_API_URL||'http://127.0.0.1:8002';
 const secret=process.env.STORE_CONNECTOR_SERVICE_SECRET;
 if(!secret||secret.length<32)throw new StoreError('CONNECTOR_NOT_CONFIGURED',503);
 const url=new URL('/provider',base);
 if(!['https:','http:'].includes(url.protocol)||url.username||url.password||
  url.protocol==='http:'&&!['127.0.0.1','localhost','[::1]'].includes(url.hostname))throw new StoreError('CONNECTOR_NOT_CONFIGURED',503);
 const body=JSON.stringify(input);
 const token=jwt.sign({tenant:tenantId,body_hash:createHash('sha256').update(body).digest('hex')},secret,{algorithm:'HS256',audience:'keel-store-adapter',expiresIn:60});
 try{
  const response=await fetch(url,{method:'POST',redirect:'error',signal:AbortSignal.timeout(60000),headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json'},body});
  const reader=response.body?.getReader();if(!reader)throw Error();const chunks:Uint8Array[]=[];let length=0;
  try{for(;;){const part=await reader.read();if(part.done)break;length+=part.value.length;if(length>2*1024*1024)throw Error();chunks.push(part.value);}}
  finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
  const data=JSON.parse(Buffer.concat(chunks).toString('utf8'));
  if(!response.ok){
   const code=typeof data.detail==='string'&&(/^STORE_[A-Z_]{1,60}$/.test(data.detail)||data.detail==='CONNECTOR_NOT_CONFIGURED')?data.detail:'STORE_SERVICE_UNAVAILABLE';
   throw new StoreError(code,response.status===401||response.status>=500?503:400);
  }
  return data;
 }catch(error){if(error instanceof StoreError)throw error;throw new StoreError('STORE_SERVICE_UNAVAILABLE',503);}
}

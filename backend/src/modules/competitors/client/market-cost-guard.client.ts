import {COMPETITOR_AI_ACTIONS_ENABLED} from '../service/competitor-capabilities.js';
import {execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
export type CollectionCostDecision={allowed:boolean;reason:string|null};
export function collectionCostDecision(tenantId:string,sourceId:string):Promise<CollectionCostDecision> {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return Promise.reject(new Error('INTEGRATION_DISABLED'));
 if(!process.env.MARKET_AI_CODEBASE_PATH) return Promise.reject(new Error('COST_GUARD_NOT_CONFIGURED'));
 const script=fileURLToPath(new URL('../../../../scripts/market-tracking-cost-guard.py',import.meta.url));
 return new Promise((resolve,reject)=>{
  const child=execFile(process.env.MARKET_AI_PYTHON||'python3',[script],{timeout:8000,maxBuffer:16384},(error,stdout)=>{
   if(error){reject(new Error('COST_GUARD_UNAVAILABLE'));return;}
   try{const result=JSON.parse(stdout.trim());if(typeof result.allowed!=='boolean')throw new Error();resolve({allowed:result.allowed,reason:typeof result.reason==='string'?result.reason.slice(0,2000):null});}catch{reject(new Error('COST_GUARD_UNAVAILABLE'));}
  });
  child.stdin?.on('error',()=>{});
  child.stdin?.end(JSON.stringify({tenant_id:tenantId,source_id:sourceId}));
 });
}
export async function collectionCostAllowed(tenantId:string,sourceId:string):Promise<boolean> {
 return (await collectionCostDecision(tenantId,sourceId)).allowed;
}

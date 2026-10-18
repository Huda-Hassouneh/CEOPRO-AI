import {COMPETITOR_AI_ACTIONS_ENABLED} from '../service/competitor-capabilities.js';
import {execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
export type ProductPreview={checked:boolean;compatible:boolean;reason:string;[key:string]:unknown};
export function checkProductPreview(input:Record<string,unknown>):Promise<ProductPreview> {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return Promise.resolve({checked:false,compatible:false,reason:'INTEGRATION_DISABLED'});
  if(!process.env.MARKET_AI_CODEBASE_PATH) return Promise.resolve({checked:false,compatible:false,reason:'CHECKER_NOT_CONFIGURED'});
  return new Promise(resolve=>{
    const child=execFile(process.env.MARKET_AI_PYTHON||'python3',[fileURLToPath(new URL('../../../../scripts/competitor-product-check.py',import.meta.url))],
      {timeout:25000,maxBuffer:65536},(error,stdout)=>{
        try {
          if(error) throw error;
          const result=JSON.parse(stdout.trim());
          if(typeof result.checked!=='boolean' || typeof result.compatible!=='boolean' || typeof result.reason!=='string') throw new Error('Invalid preview');
          resolve(result);
        } catch {resolve({checked:false,compatible:false,reason:'CHECKER_UNAVAILABLE'});}
      });
    child.stdin?.on('error',()=>{});
    child.stdin?.end(JSON.stringify(input));
  });
}

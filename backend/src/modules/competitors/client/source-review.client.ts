import {COMPETITOR_AI_ACTIONS_ENABLED} from '../service/competitor-capabilities.js';
import {execFile} from 'node:child_process';
import {fileURLToPath} from 'node:url';
export type TechnicalReview = {allowed:boolean|null;reason:string};
export function checkSourceRobots(urls:string[]):Promise<TechnicalReview> {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return Promise.resolve({allowed:null,reason:'INTEGRATION_DISABLED'});
  if(!process.env.MARKET_AI_CODEBASE_PATH) return Promise.resolve({allowed:null,reason:'CHECKER_NOT_CONFIGURED'});
  const script=fileURLToPath(new URL('../../../../scripts/competitor-source-check.py',import.meta.url));
  return new Promise(resolve=>{
    const child=execFile(process.env.MARKET_AI_PYTHON||'python3',[script],{timeout:25000,maxBuffer:16384},(error,stdout)=>{
      try {
        if(error) throw error;
        const result=JSON.parse(stdout.trim());
        if(![true,false,null].includes(result.allowed) || typeof result.reason!=='string') throw new Error();
        resolve({allowed:result.allowed,reason:result.reason});
      } catch {resolve({allowed:null,reason:'CHECKER_UNAVAILABLE'});}
    });
    child.stdin?.on('error',()=>{});
    child.stdin?.end(JSON.stringify({urls}));
  });
}

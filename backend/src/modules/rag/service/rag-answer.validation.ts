import {z} from "zod";
export const ragHistorySchema=z.array(z.object({role:z.enum(['user','assistant']),content:z.string().trim().min(1).max(6000)}).strict()).max(20);
export function boundedHistory(history:Array<{role:'user'|'assistant';content:string}>){
 let remaining=24000;
 const selected=[];
 for(const entry of history.slice(-20).reverse()){
  const content=entry.content.slice(0,Math.min(6000,remaining));
  if(!content)break;selected.push({...entry,content});remaining-=content.length;
 }
 return selected.reverse();
}
export function validTotalTokens(usage:Record<string,unknown>|undefined):number|null {
 const integer=(v:unknown)=>typeof v==='number'&&Number.isSafeInteger(v)&&v>=0&&v<=2147483647?v:
  typeof v==='string'&&/^\d+$/.test(v)&&Number.isSafeInteger(Number(v))&&Number(v)<=2147483647?Number(v):null;
 if(!usage)return null;
 const rawTotal=usage.total_tokens??usage.totalTokens??usage.total;
 const total=integer(rawTotal);
 if(rawTotal!==undefined && total===null)return null;
 const rawInput=usage.input_tokens??usage.prompt_tokens,rawOutput=usage.output_tokens??usage.completion_tokens;
 if(rawInput!==undefined || rawOutput!==undefined){
  const input=integer(rawInput),output=integer(rawOutput);
  if(input===null || output===null)return null;
  const sum=input+output;
  if(sum<=0 || sum>2147483647 || (total!==null&&total!==sum))return null;
  return sum;
 }
 return total!==null&&total>0?total:null;
}
export function normalizedEvidence(text:string):string {
 return text.normalize('NFKC').replace(/\u00ad/g,'').replace(/\s+/gu,' ').trim();
}
export function evidenceIsInSource(quote:string,text:string):boolean {
 const normalized=normalizedEvidence(quote);
 return normalized.length>0 && normalizedEvidence(text).includes(normalized);
}

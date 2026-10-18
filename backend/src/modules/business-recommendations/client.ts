import {createHmac} from 'node:crypto';
import {z} from 'zod';
export const findingSchema=z.object({logical_key:z.uuid(),rule_id:z.string().min(1).max(200),product_id:z.uuid().nullable(),
 product_name:z.union([z.record(z.string(),z.unknown()),z.string()]).nullable(),category:z.enum(['pricing','sentiment','demand','causal_timing','assortment']),
 priority:z.enum(['high','medium','low']),message:z.string().min(1).max(4000),evidence:z.record(z.string(),z.unknown())});
export const insightResponseSchema=z.object({recommendations:z.array(findingSchema).max(500),generated_at:z.iso.datetime({offset:true}),
 complete:z.boolean(),products_checked:z.number().int().nonnegative(),engine_version:z.number().int().positive()});
export type Finding=z.infer<typeof findingSchema>;
export async function requestBusinessInsights(authorization:string){
 const base=process.env.BUSINESS_INSIGHTS_API_URL?.trim()||'http://127.0.0.1:8001';
 const url=new URL('/business-recommendations?limit=500',base);
 if(!['http:','https:'].includes(url.protocol)||url.username||url.password)throw new Error('Invalid BUSINESS_INSIGHTS_API_URL');
 const secret=process.env.JWT_SECRET;if(!secret)throw new Error('JWT_SECRET is not configured');
 const signature=createHmac('sha256',secret).update('keel:business-insights:'+authorization).digest('hex');
 const response=await fetch(url,{headers:{Authorization:authorization,'X-Keel-Insights-Signature':signature},signal:AbortSignal.timeout(60000),redirect:'error'});
 if(!response.ok)throw new Error('Business insight service returned '+response.status);
 const reader=response.body?.getReader();if(!reader)throw new Error('Empty insight service response');
 const chunks:Uint8Array[]=[];let length=0;
 try{for(;;){const part=await reader.read();if(part.done)break;length+=part.value.length;if(length>4*1024*1024)throw new Error('Insight response exceeds limit');chunks.push(part.value);}}
 finally{await reader.cancel().catch(()=>{});reader.releaseLock();}
 return insightResponseSchema.parse(JSON.parse(Buffer.concat(chunks).toString('utf8')));
}

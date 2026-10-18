// Opt-in diagnostic. Sends only synthetic product histories to the public
// deployed CPU forecast endpoint. Does not read/write the application database.
import assert from 'node:assert/strict';
import { requestDemandForecast } from '../../src/modules/forecasting/client/forecasting.client.ts';
import { readGradioSseResult } from '../../src/integrations/ai/sse.ts';
if(process.env.KEEL_LIVE_FORECAST_CONTRACT !== '1') {console.error('Set KEEL_LIVE_FORECAST_CONTRACT=1 to run the synthetic live API probe.');process.exit(2);}
const base='https://hhuuddaa-ceopro-ai-analytics.hf.space';
const client={async call({apiName,data}){
  const submitted=await fetch(`${base}/gradio_api/call/${apiName}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data}),signal:AbortSignal.timeout(30000)});
  assert.equal(submitted.status,200);const {event_id}=await submitted.json();
  assert.match(event_id,/^[A-Za-z0-9_-]{1,256}$/);
  const result=await fetch(`${base}/gradio_api/call/${apiName}/${event_id}`,{signal:AbortSignal.timeout(60000)});
  assert.equal(result.status,200);return readGradioSseResult(result.body,60000);
}};
for(const days of [21,60]){
 const productName='KEEL Diagnostics Product';
 const transactions=Array.from({length:days},(_,i)=>({transaction_date:new Date(Date.UTC(2026,7,1+i)).toISOString().slice(0,10),quantity:8+i%7,unit_price:5}));
 const out=await requestDemandForecast({transactions,productName,horizonDays:7,currentPrice:5,currentStock:null,currency:'USD'},client);
 assert.equal(out.result.status,'OK');assert.equal(out.product_name,productName);assert.equal(out.transactions_used,days);
 console.log(`PASS live production payload builder, SSE parser and response validation: ${days} days, source=${out.result.source}`);
}

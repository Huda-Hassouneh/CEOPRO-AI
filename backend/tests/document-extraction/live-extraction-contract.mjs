// Sends synthetic files only; never connects to a customer database.
import assert from 'node:assert/strict';
import * as xlsx from 'xlsx';
import {uploadExtractionFile} from '../../src/modules/dataconnection/client/ingestion.client.ts';
import {validateExtractionResultForDataConnection} from '../../src/modules/dataconnection/validators/extraction-result.validation.ts';
import {readGradioSseResult} from '../../src/integrations/ai/sse.ts';
if(process.env.DOCUMENT_EXTRACTION_LIVE_AI!=='1')throw new Error('Set DOCUMENT_EXTRACTION_LIVE_AI=1 for synthetic public-service verification.');
const base='https://hhuuddaa-ceopro-ai-analytics.hf.space';
const client={async call({apiName,data}){
 const submitted=await fetch(`${base}/gradio_api/call/${apiName}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data}),signal:AbortSignal.timeout(30000)});
 assert.equal(submitted.status,200);const {event_id}=await submitted.json();assert.match(event_id,/^[A-Za-z0-9_-]{1,256}$/);
 const response=await fetch(`${base}/gradio_api/call/${apiName}/${event_id}`,{signal:AbortSignal.timeout(60000)});
 assert.equal(response.status,200);return readGradioSseResult(response.body,60000);
}};
const csv='product_name,quantity,unit_price,currency,transaction_date\nKEEL Synthetic Tea,2,10,JOD,2026-10-01\n';
const book=xlsx.read(csv,{type:'string',raw:true});
for(const [name,buffer] of [['synthetic.csv',Buffer.from(csv)],['synthetic.xlsx',xlsx.write(book,{type:'buffer',bookType:'xlsx'})]]){
 const result=await uploadExtractionFile({file:{originalname:name,buffer}},client);
 assert.equal(validateExtractionResultForDataConnection(result),null);assert.equal(result.summary.row_outcomes.length,1);
 console.log(`PASS live ${name}: actual request builder, SSE parser and complete response validation`);
}

import test from 'node:test';import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import {mapRagSources,mapRagReply,mapRagTurns,reuseRagRequest} from '../src/features/knowledge-base/utils/ragChatContract.js';
const source={document_id:'real-document',chunk_id:'real-chunk',source_index:1,document:'Policy.pdf',text:'Delivery costs 7 JOD.',score:0.9};
test('citations keep independent document/chunk IDs, filename, and evidence text',()=>{
 const [mapped]=mapRagSources([source]);assert.equal(mapped.documentId,'real-document');assert.equal(mapped.chunkId,'real-chunk');assert.equal(mapped.documentName,'Policy.pdf');assert.equal(mapped.excerpt,source.text);
});
test('restored turns preserve stable identities and hide invalidated answers',()=>{
 const response={request_id:'id',session_id:'s',answer:'7 JOD',sources:[source],evidence_status:'supported'};
 assert.equal(mapRagReply(response).messageId,'id-assistant');
 const turns=mapRagTurns([{request_id:'id',question:'How much?',response,created_at:'2026-10-15'},{request_id:'removed',question:'Old?',response:null,status:'unavailable'}],key=>key);
 assert.equal(turns.length,4);assert.equal(turns[1].content,'7 JOD');assert.equal(turns[3].content,'ragAssistant.history.unavailable');
});
test('uncertain network errors reuse request IDs; definitive failures can start new requests',()=>{
 assert.equal(reuseRagRequest({code:'ERR_NETWORK'}),true);
 const error=(code,status)=>({response:{status,data:{error:{code}}}});
 assert.equal(reuseRagRequest(error('RAG_REQUEST_PENDING',409)),true);
 assert.equal(reuseRagRequest(error('RAG_REQUEST_FAILED',409)),false);
 assert.equal(reuseRagRequest(error('RAG_CITATION_INVALID',502)),false);
 assert.equal(reuseRagRequest(error('RAG_USAGE_METADATA_INVALID',502)),false);
});
test('history, search and error messages are localized with English/Arabic parity',()=>{
 const read=lang=>JSON.parse(readFileSync(new URL(`../src/assets/locales/${lang}.json`,import.meta.url))).ragAssistant;
 for(const group of ['history','search','errors'])assert.deepEqual(Object.keys(read('en')[group]).sort(),Object.keys(read('ar')[group]).sort());
});

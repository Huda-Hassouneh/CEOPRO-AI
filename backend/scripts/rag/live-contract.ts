import 'dotenv/config';
import assert from 'node:assert/strict';
import {queryRagAi} from '../../src/modules/rag/client/rag.client.js';
import {validTotalTokens,evidenceIsInSource} from '../../src/modules/rag/service/rag-answer.validation.js';
assert.equal(process.env.RAG_LIVE_AI,'1','Explicit opt-in required: set RAG_LIVE_AI=1. Uses synthetic data and the configured hosted AI.');
const text='SYNTHETIC TEST FIXTURE: Zephyr delivery costs 7 JOD. Delivery is free for orders of 30 JOD or more. No monthly profit figure is provided.';
const documents=[{file_name:'synthetic-policy.md',text}];
const question='What does Zephyr delivery cost?';
const first=await queryRagAi({documents,queryText:question,topK:3,history:null});
for(const source of first.sources){assert.equal(source.document,documents[0]!.file_name);assert(evidenceIsInSource(source.text,text));}
assert(first.sources.length>0);assert(validTotalTokens(first.token_usage)!==null);
assert.match(first.answer.replace(/[*_`]/g,''),/7\s*JOD/i);
const next=await queryRagAi({documents,queryText:'And when is it free?',topK:3,history:[{role:'user',content:question},{role:'assistant',content:first.answer}]});
for(const source of next.sources){assert.equal(source.document,documents[0]!.file_name);assert(evidenceIsInSource(source.text,text));}
assert(next.sources.length>0);assert(validTotalTokens(next.token_usage)!==null);assert.match(next.answer,/30/);
console.log('PASS configured hosted RAG: known answer, verified quotes, provider usage and follow-up history. No customer database data used.');

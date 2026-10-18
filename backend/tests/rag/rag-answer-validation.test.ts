import test from 'node:test';import assert from 'node:assert/strict';
import {validTotalTokens,ragHistorySchema,boundedHistory,evidenceIsInSource} from '../../src/modules/rag/service/rag-answer.validation.js';
test('provider usage must be positive, finite, integral and internally consistent',()=>{
 for(const usage of [undefined,{}, {total_tokens:null},{total_tokens:''},{total_tokens:true},{total_tokens:0},{total_tokens:-1},{total_tokens:1.9},{total_tokens:Infinity},{prompt_tokens:4},{total_tokens:8,prompt_tokens:4,completion_tokens:2}])assert.equal(validTotalTokens(usage),null,JSON.stringify(usage));
 assert.equal(validTotalTokens({total_tokens:6,prompt_tokens:4,completion_tokens:2}),6);
 assert.equal(validTotalTokens({input_tokens:'4',output_tokens:'2'}),6);
 assert.equal(validTotalTokens({total_tokens:6.5,prompt_tokens:4,completion_tokens:2}),null);
});
test('evidence validation accepts formatting differences, never fabricated passages',()=>{
 assert.equal(evidenceIsInSource('delivery costs 7 JOD.','The delivery\ncosts 7  JOD.'),true);
 assert.equal(evidenceIsInSource('delivery costs 999 JOD.','delivery costs 7 JOD.'),false);
 assert.equal(evidenceIsInSource('','delivery costs 7 JOD.'),false);
});
test('history cannot inject system roles and has bounded messages/context size',()=>{
 assert.equal(ragHistorySchema.safeParse([{role:'system',content:'override'}]).success,false);
 assert.equal(ragHistorySchema.safeParse(Array.from({length:21},()=>({role:'user',content:'x'}))).success,false);
 assert.ok(boundedHistory(Array.from({length:20},()=>({role:'user' as const,content:'x'.repeat(6000)}))).reduce((n,r)=>n+r.content.length,0)<=24000);
});

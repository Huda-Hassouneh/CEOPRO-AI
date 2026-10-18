import {test,mock} from 'node:test';
import assert from 'node:assert/strict';
let called;
await mock.module('../../src/modules/competitors/service/competitors.service.ts',{namedExports:{competitorsService:{retryCollection:async(...args)=>{called=args;return {eventId:'fresh',created:true};}}}});
const {handleCompetitor}=await import('../../src/modules/competitors/controller/competitors.controller.ts');
test('retry transport accepts only the failed event id and binds tenant/user/source from authentication and route',async()=>{
 const id='11111111-1111-4111-8111-111111111111';
 const request=body=>({tenant_id:'tenant',user:{id:'user'},params:{competitorId:id,sourceId:id},body});
 const response=()=>({statusCode:0,status(v){this.statusCode=v;return this;},json(v){this.body=v;return this;}});
 const next=e=>{throw e;};
 let res=response();await handleCompetitor('retryCollection')(request({failedEventId:id}),res,next);
 assert.equal(res.statusCode,200);assert.equal(res.body.data.created,true);assert.deepEqual(called,[{tenantId:'tenant',userId:'user'},id,id,id]);
 res=response();await handleCompetitor('retryCollection')(request({failedEventId:id,tenantId:'other'}),res,next);assert.equal(res.statusCode,400);
 res=response();const req=request({failedEventId:id});req.params.sourceId='bad';await handleCompetitor('retryCollection')(req,res,next);assert.equal(res.statusCode,400);
 res=response();await handleCompetitor('retryCollection')(request({}),res,next);assert.equal(res.statusCode,400);
});

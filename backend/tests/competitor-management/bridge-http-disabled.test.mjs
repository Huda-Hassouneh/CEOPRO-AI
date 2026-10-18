import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
let calls=[];
const operations=['list','profile','update','create','track','discover','cancelDiscovery','schedule','confirm','reviewSource','retryCollection','linkProduct','previewProduct','rejectCandidate','catalogProducts','productCandidates'];
const repo=Object.fromEntries(operations.map(name=>[name,async()=>{calls.push(name);return name==='list'?{competitors:[],capacity:{},canEdit:true}:{id:'saved'};} ]));
await mock.module('../../src/modules/competitors/repo/competitors.repo.ts',{namedExports:{competitorsRepo:repo}});
const {competitorsService}=await import('../../src/modules/competitors/service/competitors.service.ts');
const {handleCompetitor}=await import('../../src/modules/competitors/controller/competitors.controller.ts');
const response=()=>({code:0,body:null,status(code){this.code=code;return this;},json(body){this.body=body;return this;}});
const request={tenant_id:'tenant',user:{id:'user'},params:{competitorId:'11111111-1111-4111-8111-111111111111'},query:{},body:{alias:'Display name'}};
test('every dependent service and authenticated HTTP operation rejects before repository calls',async()=>{
 for(const op of operations.filter(name=>!['list','profile','update'].includes(name))){
  assert.throws(()=>competitorsService[op](),e=>e.code==='NOT_IMPLEMENTED');
  const res=response();await handleCompetitor(op)(request,res,e=>{throw e;});
  assert.equal(res.code,501);assert.equal(res.body.error.code,'NOT_IMPLEMENTED');
 }
 assert.deepEqual(calls,[]);
});
test('directory reads and alias editing retain their existing HTTP contracts',async()=>{
 for(const op of ['list','profile','update']){const res=response();await handleCompetitor(op)(request,res,e=>{throw e;});assert.equal(res.code,200);}
 assert.deepEqual(calls,['list','profile','update']);
});

/* Standalone non-TTY worker logging test. No database connection. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const ts=require('typescript');
const vm=require('node:vm');
const file=path.join(__dirname,'../src/workers/data-ingestion.worker.ts');
const source=fs.readFileSync(file,'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const logs=[];
const signals={};
let disconnects=0, called=0;
const job={job_id:'12345678-0000-0000-0000-000000000000',tenant_id:'11111111-1111-1111-1111-111111111111',processing_attempts:1};
const fakeProcess={stdout:{isTTY:false,write:()=>{},columns:120},env:{NODE_ENV:'test'},on:(signal,cb)=>{signals[signal]=cb},exit:()=>{throw Error('unexpected exit')}};
const repo={
  markExhaustedLeasesFailed: async()=>0,
  claimPendingJobs:async()=> called++===0?[job]:[],
  processClaimedJob:async(j,onProgress)=>{
    assert.equal(j.job_id,job.job_id);
    const sample={phase:'started',jobId:job.job_id,attempt:1,totalRows:100,completedRows:0,pendingRows:100,committedRows:0,invalidRows:0,partialRows:0,batchNumber:0,batchRows:0,batchDurationMs:0};
    onProgress(sample);
    onProgress({...sample,phase:'batch',completedRows:50,pendingRows:50,committedRows:50,batchNumber:1,batchRows:50,batchDurationMs:1000});
    onProgress({...sample,phase:'completed',completedRows:100,pendingRows:0,committedRows:100,batchNumber:2,batchRows:50,batchDurationMs:1000});
    signals.SIGINT();
    return {jobId:job.job_id,committed:100,quarantined:0};
  }
};
const fakeRequire=(id)=>{
  if(id==='node:readline')return require('node:readline');
  if(id.includes('ingestion-worker-database'))return {ingestionWorkerPrisma:{$disconnect:async()=>{disconnects++}}};
  if(id.includes('ingestion-worker.repo'))return {ingestionWorkerRepo:repo};
  throw Error('Unexpected import '+id);
};
const output={exports:{}};
vm.runInNewContext(compiled,{module:output,exports:output.exports,require:fakeRequire,console:{info:(...a)=>logs.push(a.join(' ')),warn:(...a)=>logs.push(a.join(' ')),error:(...a)=>logs.push(a.join(' '))},process:fakeProcess,Date,Map,Promise,setTimeout,clearTimeout,setInterval,clearInterval});
setTimeout(()=>{
  try {
    assert.ok(logs.some(x=>x.includes('0.0%')&&x.includes('0/100')),logs.join('\n'));
    assert.ok(logs.some(x=>x.includes('50.0%')&&x.includes('50/100')),logs.join('\n'));
    assert.ok(logs.some(x=>x.includes('Job completed')&&x.includes('committed=100')),logs.join('\n'));
    assert.equal(disconnects,1);
    console.log('PASS: non-TTY logs include started, committed batch progress and completion; worker disconnected once');
  } catch (e) {console.error(e);process.exitCode=1}
},25);

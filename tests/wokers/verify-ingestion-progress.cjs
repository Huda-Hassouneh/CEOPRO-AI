/* Self-contained in-memory contract simulation: no database/network needed.
 * Run: node verify-ingestion-batches.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const ts = require('typescript');
const repoPath = path.join(__dirname,'../src/modules/dataconnection/repo/ingestion-worker.repo.ts');
const source = fs.readFileSync(repoPath,'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{module: ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const tenantId='11111111-1111-1111-1111-111111111111';
const jobId='22222222-2222-2222-2222-222222222222';
let state = {
  job: {tenant_id:tenantId,job_id:jobId,job_status:'PROCESSING',processing_attempts:2,rows_processed:0,rows_failed:0,rows_quarantined:0,rows_partial:0},
  staging: Array.from({length:1000},(_,i)=> ({staging_row_id:BigInt(i+1),tenant_id:tenantId,job_id:jobId,validation_status:i<5?'PARTIAL':i<8?'INVALID':'PENDING',raw_payload_json:{product_name:`Flower ${i%20}`,quantity:1,unit_price:'10.0000',total_price:'10.0000',currency:'JOD',transaction_date:'2026-10-08',ok:i!==99}})),
  products:[], transactions:[]
};
let txCount=0, maximumRowsInBatch=0, injectOnce=true;
const matchWhere=(r,w)=> Object.entries(w).every(([k,v])=>r[k]===v);
function applyData(target,data){for(const [k,v] of Object.entries(data)){target[k]=v && typeof v==='object' && 'increment' in v?(target[k]??0)+v.increment:v;}}
function client(s){
  return {
    $queryRaw:async (strings,...vals)=> {
      const sql=strings.join('?');
      if(sql.includes('SELECT job_id') && sql.includes('FOR UPDATE')) return s.job.job_status==='PROCESSING' && s.job.processing_attempts===vals[2] ?[{job_id:jobId}]:[];
      if(sql.includes('WITH product_name_lock')){
        const p=s.products.find(p=>p.tenant_id===vals[1]&&p.product_name.en.trim().toLowerCase()===vals[2]);
        return [{product_id:p?.product_id??null}];
      }
      throw Error('Unexpected SQL in contract simulation: '+sql.slice(0,130));
    },
    import_staging_rows:{
      findMany:async({where,take})=>{const rows=s.staging.filter(r=>matchWhere(r,where));maximumRowsInBatch=Math.max(maximumRowsInBatch,rows.slice(0,take).length);return rows.slice(0,take).map(r=>({staging_row_id:r.staging_row_id,raw_payload_json:r.raw_payload_json}));},
      update:async({where,data})=>{const r=s.staging.find(x=>x.staging_row_id===where.staging_row_id);assert.ok(r);applyData(r,data);return r;},
      count:async({where})=>s.staging.filter(r=>matchWhere(r,where)).length
    },
    products:{create:async({data})=>{s.products.push(data);return {product_id:data.product_id};}},
    transactions:{create:async({data})=>{if(injectOnce&&txCount===3&&s.transactions.length>=120){injectOnce=false;throw Error('simulated database connection failure');}s.transactions.push(data);return {transaction_id:data.transaction_id};}},
    ingestion_jobs:{update:async({data})=>{applyData(s.job,data);return s.job;}}
  };
}
const prisma={
  import_staging_rows:{groupBy:async({where})=> {
    const groups=new Map();
    for(const r of state.staging.filter(r=>r.tenant_id===where.tenant_id && r.job_id===where.job_id)) groups.set(r.validation_status,(groups.get(r.validation_status)||0)+1);
    return [...groups].map(([validation_status,n])=>({validation_status,_count:{_all:n}}));
  }},
  $transaction:async (fn,opts)=>{txCount++;assert.equal(opts.timeout,60000);const clone=structuredClone(state);const result=await fn(client(clone));state=clone;return result;},
  ingestion_jobs:{ updateMany:async({where,data})=>{
    if(someWhere(state.job,where)){applyData(state.job,data);return {count:1};}return {count:0};
  }}
};
function someWhere(row,where){return Object.entries(where).every(([k,v])=>row[k]===v);}
const sandboxModule={exports:{}};
const fakeRequire=(name)=>{
  if(name==='node:crypto')return require('node:crypto');
  if(name.includes('ingestion-worker-database'))return {ingestionWorkerPrisma:prisma};
  if(name.includes('sales-staging-row'))return {parseSalesStagingRow:(r)=>r.ok===false?{ok:false,error:'invalid sale'}:{ok:true,value:{productName:r.product_name,quantity:r.quantity,unitPrice:r.unit_price,totalPrice:r.total_price,currency:r.currency,transactionDate:new Date(r.transaction_date)}}};
  throw Error('Unrecognized runtime import '+name);
};
vm.runInNewContext(compiled,{module:sandboxModule,exports:sandboxModule.exports,require:fakeRequire,Date,Map,console,setTimeout});
const repo=sandboxModule.exports.ingestionWorkerRepo;
(async()=>{
  const progressFirst=[];
  await assert.rejects(repo.processClaimedJob({tenant_id:tenantId,job_id:jobId,processing_attempts:2},p=>progressFirst.push({...p})),/simulated database/);
  assert.equal(progressFirst[0].phase,'started');
  assert.equal(progressFirst[0].totalRows,1000);
  assert.equal(progressFirst[0].completedRows,8); // extraction-time INVALID/PARTIAL already resolved
  assert.equal(progressFirst.at(-1).completedRows,108); // only two successfully committed batches
  assert.ok(progressFirst.every((p,i)=> i===0 || p.completedRows>=progressFirst[i-1].completedRows));
  // 2 committed chunks survive, third one is entirely rolled back.
  assert.equal(state.staging.filter(r=>r.validation_status==='COMMITTED').length,99);
  assert.equal(state.transactions.length,99);
  assert.equal(state.job.rows_processed,99);
  await repo.scheduleRetryOrFail({tenant_id:tenantId,job_id:jobId,processing_attempts:2},{code:'SIMULATED'});
  assert.equal(state.job.job_status,'QUEUED');
  state.job.job_status='PROCESSING';state.job.processing_attempts=3;
  assert.equal(await repo.processClaimedJob({tenant_id:tenantId,job_id:jobId,processing_attempts:2}),null,'old attempt must not mutate state');
  const progressResume=[];
  const result=await repo.processClaimedJob({tenant_id:tenantId,job_id:jobId,processing_attempts:3},p=>progressResume.push({...p}));
  assert.equal(progressResume[0].completedRows,108, 'retry starts at durable committed progress');
  assert.equal(progressResume.at(-1).phase,'completed');
  assert.equal(progressResume.at(-1).completedRows,1000);
  assert.equal(progressResume.at(-1).pendingRows,0);
  assert.equal(progressResume.at(-1).committedRows,991);
  assert.equal(progressResume.at(-1).invalidRows,4);
  assert.equal(progressResume.at(-1).partialRows,5);
  assert.ok(progressResume.every((p,i)=>i===0||p.completedRows>=progressResume[i-1].completedRows));
  assert.equal(result.committed,991);
  assert.equal(result.quarantined,4);
  assert.equal(state.transactions.length,991);
  assert.equal(new Set(state.transactions.map(x=>x.transaction_id)).size,991);
  assert.equal(state.staging.filter(r=>r.validation_status==='PENDING').length,0);
  assert.equal(state.job.rows_processed,991);
  assert.equal(state.job.rows_failed,4);
  assert.equal(state.job.rows_quarantined,4);
  assert.equal(state.job.rows_partial,5);
  assert.equal(state.job.job_status,'COMPLETED');
  assert.ok(maximumRowsInBatch<=50);
  assert.ok(txCount>20);
  console.log(`PASS: 1,000 staged rows, commit-only progress, resumed at 108/1000, final 1000/1000, ${state.transactions.length} sales, rolled-back batch excluded, stale-claim protection, max batch ${maximumRowsInBatch}; ${txCount} short transactions`);
})().catch(e=>{console.error(e);process.exitCode=1});

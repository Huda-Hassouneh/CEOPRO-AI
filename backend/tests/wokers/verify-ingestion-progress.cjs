/* Self-contained in-memory contract simulation: no database/network needed.
 * Run: node verify-ingestion-batches.cjs
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const esbuild = require('esbuild');
const repoPath = path.join(__dirname,'../../src/modules/dataconnection/repo/ingestion-worker.repo.ts');
const source = fs.readFileSync(repoPath,'utf8');
const compiled = esbuild.transformSync(source,{loader:'ts',format:'cjs',target:'es2022'}).code;
const tenantId='11111111-1111-1111-1111-111111111111';
const jobId='22222222-2222-2222-2222-222222222222';
let state = {
  job: {tenant_id:tenantId,job_id:jobId,job_status:'PROCESSING',processing_attempts:2,rows_processed:0,rows_failed:0,rows_quarantined:0,rows_partial:0},
  staging: Array.from({length:1000},(_,i)=> ({staging_row_id:BigInt(i+1),tenant_id:tenantId,job_id:jobId,validation_status:i<5?'PARTIAL':i<8?'INVALID':'PENDING',raw_payload_json:{product_name:`Flower ${i%20}`,quantity:1,unit_price:'10.0000',total_price:'10.0000',currency:'JOD',transaction_date:'2026-10-08',ok:i!==99}})),
  products:[], transactions:[]
};
let capacityLimit=Infinity, catalogLocks=0;
class ProductError extends Error { constructor(code){super(code);this.code=code;} }
let txCount=0, maximumRowsInBatch=0, injectOnce=true, bulkSalesWrites=0, bulkMarkerWrites=0;
const matchWhere=(r,w)=> Object.entries(w).every(([k,v])=>r[k]===v);
function applyData(target,data){for(const [k,v] of Object.entries(data)){target[k]=v && typeof v==='object' && 'increment' in v?(target[k]??0)+v.increment:v;}}
function client(s){
  return {
    _productCount:()=>s.products.filter(p=>!p.deleted_at).length,
    $queryRaw:async (strings,...vals)=> {
      const sql=strings.join('?');
      if(sql.includes('SELECT job_id') && sql.includes('FOR UPDATE')) return s.job.job_status==='PROCESSING' && s.job.processing_attempts===vals[2] ?[{job_id:jobId}]:[];
      if(sql.includes('WITH product_name_lock')){
        const matches=s.products.filter(p=>p.tenant_id===vals[1] && (vals[2] ? p.sku?.toLowerCase()===vals[2].toLowerCase() : [p.product_name.en,...(p.metadata?.import_name_aliases||[])].some(n=>n?.trim().toLowerCase()===vals[4]))).sort((a,b)=>Number(Boolean(a.deleted_at))-Number(Boolean(b.deleted_at))).slice(0,2);
        return matches.length ? matches.map(p=>({product_id:p.product_id,deleted_at:p.deleted_at||null})) : [{product_id:null,deleted_at:null}];
      }
      throw Error('Unexpected SQL in contract simulation: '+sql.slice(0,130));
    },
    import_staging_rows:{
      findMany:async({where,take})=>{const rows=s.staging.filter(r=>matchWhere(r,where));maximumRowsInBatch=Math.max(maximumRowsInBatch,rows.slice(0,take).length);return rows.slice(0,take).map(r=>({staging_row_id:r.staging_row_id,raw_payload_json:r.raw_payload_json}));},
      update:async({where,data})=>{const r=s.staging.find(x=>x.staging_row_id===where.staging_row_id);assert.ok(r);applyData(r,data);return r;},
      count:async({where})=>s.staging.filter(r=>matchWhere(r,where)).length
    },
    products:{create:async({data})=>{s.products.push(data);return {product_id:data.product_id};}},
    transactions:{createMany:async({data})=>{bulkSalesWrites++;if(injectOnce&&txCount===3){injectOnce=false;throw Error('simulated database connection failure');}s.transactions.push(...data);return {count:data.length};}},
    $executeRawUnsafe:async(sql,...params)=>{
      assert.match(sql,/UPDATE import_staging_rows AS staging/);
      bulkMarkerWrites++;
      const [expectedTenant,expectedJob]=params.slice(-2);
      let changed=0;
      for(let i=0;i<params.length-2;i+=2){
        const [id,transactionId]=params.slice(i,i+2);
        const row=s.staging.find(r=>r.staging_row_id===id&&r.tenant_id===expectedTenant&&r.job_id===expectedJob&&r.validation_status==='PENDING');
        if(!row)continue;
        applyData(row,{validation_status:'COMMITTED',validation_errors:null,committed_record_id:transactionId,committed_table:'transactions'});
        changed++;
      }
      return changed;
    },
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
  if(name.includes('product-capacity'))return {lockProductCatalog:async()=>{catalogLocks++;},requireProductCapacity:async(tx)=>{if(tx._productCount()>=capacityLimit)throw new ProductError('PRODUCT_CAPACITY_EXCEEDED');}};
  if(name.includes('products.types'))return {ProductError};
  if(name.includes('sales-staging-row'))return {parseSalesStagingRow:(r)=>r.ok===false?{ok:false,error:'invalid sale'}:{ok:true,value:{productName:r.product_name,sku:r.sku||null,quantity:r.quantity,unitPrice:r.unit_price,totalPrice:r.total_price,currency:r.currency,transactionDate:new Date(r.transaction_date)}}};
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
  assert.ok(bulkSalesWrites<30);
  assert.ok(bulkMarkerWrites<30);
  const recoveredSales=state.transactions.length;
  assert.ok(catalogLocks>20);
  // New products at capacity, ambiguous names and archived matches are quarantined.
  // Matching existing products still commits, including earlier names after renaming.
  state={job:{tenant_id:tenantId,job_id:jobId,job_status:'PROCESSING',processing_attempts:4}, products:[
    {tenant_id:tenantId,product_id:'one',sku:'ONE',product_name:{en:'Same'},current_price:'99'},
    {tenant_id:tenantId,product_id:'two',sku:'TWO',product_name:{en:'Same'}},
    {tenant_id:tenantId,product_id:'old',sku:'OLD',product_name:{en:'Archived'},deleted_at:new Date()},
    {tenant_id:tenantId,product_id:'renamed',sku:null,product_name:{en:'New name'},metadata:{import_name_aliases:['old name']}}
  ],transactions:[],staging:['New','Same','Archived','Same','Old name'].map((name,i)=>({staging_row_id:BigInt(i+1),tenant_id:tenantId,job_id:jobId,validation_status:'PENDING',raw_payload_json:{product_name:name,sku:i===3?'ONE':null,quantity:1,unit_price:'2',total_price:'2',currency:'JOD',transaction_date:'2026-10-08'}}))};
  capacityLimit=3;
  const edge=await repo.processClaimedJob({tenant_id:tenantId,job_id:jobId,processing_attempts:4});
  assert.equal(edge.committed,2);assert.equal(edge.quarantined,3);
  assert.deepEqual(state.transactions.map(row=>row.product_id),['one','renamed']);
  assert.equal(state.products.length,4);assert.equal(state.products[0].current_price,'99','import must not overwrite maintained price');
  assert.match(state.staging[0].validation_errors,/active product limit/);
  assert.match(state.staging[1].validation_errors,/More than one/);
  assert.match(state.staging[2].validation_errors,/archived/);
  console.log('PASS: capacity quarantine, ambiguous and archived matching, SKU identity, renamed import aliases, existing-product commits at cap');
  console.log(`PASS: 1,000 staged rows, commit-only progress, resumed at 108/1000, final 1000/1000, ${recoveredSales} sales, rolled-back batch excluded, stale-claim protection, max batch ${maximumRowsInBatch}; ${bulkSalesWrites} bulk sale writes and ${bulkMarkerWrites} bulk marker writes`);
})().catch(e=>{console.error(e);process.exitCode=1});

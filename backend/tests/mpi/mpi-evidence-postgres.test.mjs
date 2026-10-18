import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

test('customer-perception evidence satisfies PostgreSQL constraints for every subject as ceopro_app',async()=>{
  const db=new PGlite({extensions:{vector,pgcrypto}});
  const previous=process.env.DATABASE_URL;
  let socket,prisma;
  try {
    await db.exec(`CREATE ROLE ceopro_ai_prod_user LOGIN NOSUPERUSER NOBYPASSRLS;
      CREATE ROLE ceopro_ai_test_user LOGIN NOSUPERUSER NOBYPASSRLS;
      CREATE ROLE ceopro_ai_test_writer LOGIN NOSUPERUSER NOBYPASSRLS;`);
    const migrations=new URL('../../prisma/migrations/',import.meta.url);
    for(const name of readdirSync(migrations).filter(n=>/^\d/.test(n)).sort())
      await db.exec(readFileSync(new URL(`${name}/migration.sql`,migrations),'utf8'));
    const tenantId=randomUUID(),userId=randomUUID(),productId=randomUUID();
    await db.query(`INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency) VALUES($1,'MPI regression','JO','USD')`,[tenantId]);
    await db.query(`INSERT INTO public.users(user_id,email,password_hash) VALUES($1,$2,'test-only')`,[userId,`${userId}@mpi-regression.example`]);
    await db.query(`INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES($1,$2,'owner')`,[tenantId,userId]);
    await db.exec('SET SESSION AUTHORIZATION ceopro_app');
    await db.query(`SELECT set_config('app.current_user_id',$1,false),set_config('app.current_tenant_id',$2,false)`,[userId,tenantId]);
    const role=(await db.query('SELECT current_user AS name,session_user AS session_user')).rows[0];
    assert.equal(role.name,'ceopro_app');assert.equal(role.session_user,'ceopro_app');
    await assert.rejects(()=>db.query(`INSERT INTO public.evidence_records(tenant_id,source_module,metric_name,metric_value_json,explanation_text)
      VALUES($1,'market-intelligence','market_perception_index','{}','Provider explanation')`,[tenantId]),e=>e.code==='23514' && e.constraint==='chk_evidence_shape');
    console.log('REPRODUCED 23514/chk_evidence_shape with the original insert shape');
    await db.query("SELECT set_config('app.current_user_id','',false),set_config('app.current_tenant_id','',false)");
    socket=new PGLiteSocketServer({db,host:'127.0.0.1',port:0});await socket.start();
    process.env.DATABASE_URL=`postgresql://ceopro_app@${socket.getServerConn()}/postgres`;
    ({prisma}=await import('../../src/config/database.ts'));
    const {persistMpiEvidence}=await import('../../src/modules/mpi/repo/mpi.repo.ts');
    const evidence={explanation:'Actual provider explanation.',source_review_ids:[randomUUID(),randomUUID()],source_scope:'submitted_sample',
      observation_period:{start:'2026-10-01',end:'2026-10-14'},collection_methods:['MANUAL','PUBLIC_API'],
      eligible_review_count:6,sample_limit:100,sentiment_model:'regression-model',model_revision:'test-revision'};
    const base={tenantId,userId,status:'OK',reason:null,mpi:55.91,reviewCount:6,weightedSentimentScore:0.394,
      volumeConfidence:0.3,confidenceScore:0.57,explanationText:'  Actual provider explanation.  ',evidence,asOf:'2026-10-14',
      sampleSize:{status:'OK',minimum_required:5,observed:6},labelCounts:{positive:4,neutral:0,negative:2}};
    for(const subjectType of ['BUSINESS','PRODUCT','COMPETITOR']) {
      for(const status of ['OK','UNKNOWN']) {
        for(const explanation of [base.explanationText,null,'   ']) {
          const input={...base,subjectType,subjectId:subjectType==='BUSINESS'?undefined:productId,status,explanationText:explanation,
            ...(status==='UNKNOWN'?{reason:'MODEL_UNAVAILABLE',mpi:null,weightedSentimentScore:null,volumeConfidence:null,confidenceScore:null,labelCounts:null}: {})};
          const id=await persistMpiEvidence(input);
          const row=await prisma.$transaction(async tx=>{
            await tx.$queryRaw`SELECT set_config('app.current_user_id',${userId},true),set_config('app.current_tenant_id',${tenantId},true)`;
            return tx.evidence_records.findUnique({where:{evidence_id:id}});
          });
          assert.equal(row.category,status==='OK'?'FACT':'UNKNOWN');
          assert.equal(row.source_module,'market-intelligence');assert.equal(row.forecast_id,null);
          assert.equal(row.metric_name,'market_perception_index');
          assert.equal(row.metric_value_json.status,status);assert.equal(row.metric_value_json.mpi,input.mpi);
          assert.equal(row.metric_value_json.reason,input.reason);
          assert.equal(row.metric_value_json.subject_type,subjectType);
          assert.equal(row.metric_value_json.subject_id,input.subjectId??null);
          assert.deepEqual(row.metric_value_json.observation_period,evidence.observation_period);
          assert.deepEqual(row.metric_value_json.label_counts,input.labelCounts);
          assert.equal(row.metric_value_json.sentiment_model,evidence.sentiment_model);
          assert.equal(row.metric_value_json.model_revision,evidence.model_revision);
          assert.deepEqual(row.source_record_ids,{subject_type:subjectType,subject_id:input.subjectId??null,
            review_ids:evidence.source_review_ids,review_id_scope:'submitted_sample',collection_methods:evidence.collection_methods,sample_limit:100});
          if(explanation?.trim())assert.equal(row.explanation_text,explanation.trim());
          else assert.match(row.explanation_text,/without an explanation/);
          console.log(`PASS real Prisma ${subjectType}/${status}, explanation=${explanation===null?'null':explanation.trim()?'provided':'blank'}`);
        }
      }
    }
    const otherTenant=randomUUID();
    const crossTenant=await prisma.$transaction(async tx=>{
      await tx.$queryRaw`SELECT set_config('app.current_user_id',${userId},true),set_config('app.current_tenant_id',${otherTenant},true)`;
      return tx.evidence_records.findMany({where:{tenant_id:tenantId}});
    });
    assert.equal(crossTenant.length,0);
    console.log('PASS cross-tenant evidence remains hidden; database constraints and RLS unchanged');
  } finally {
    if(prisma)await prisma.$disconnect();if(socket)await socket.stop();await db.close();
    if(previous===undefined)delete process.env.DATABASE_URL;else process.env.DATABASE_URL=previous;
  }
});

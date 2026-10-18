import assert from 'node:assert/strict';
import test from 'node:test';
import { randomUUID } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';

test('pricing evidence satisfies actual PostgreSQL constraints as ceopro_app for OK and UNKNOWN',async()=>{
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
    await db.query(`INSERT INTO public.companies(tenant_id,business_name,country_code,primary_currency) VALUES($1,'Pricing regression','JO','USD')`,[tenantId]);
    await db.query(`INSERT INTO public.users(user_id,email,password_hash) VALUES($1,$2,'test-only')`,[userId,`${userId}@pricing-regression.example`]);
    await db.query(`INSERT INTO public.tenant_users(tenant_id,user_id,role_key) VALUES($1,$2,'owner')`,[tenantId,userId]);
    await db.exec('SET SESSION AUTHORIZATION ceopro_app');
    await db.query(`SELECT set_config('app.current_user_id',$1,false),set_config('app.current_tenant_id',$2,false)`,[userId,tenantId]);
    const role=(await db.query('SELECT current_user AS name,session_user AS session_user')).rows[0];
    assert.equal(role.name,'ceopro_app');assert.equal(role.session_user,'ceopro_app');
    await assert.rejects(()=>db.query(`INSERT INTO public.evidence_records(tenant_id,source_module,metric_name,metric_value_json,explanation_text)
      VALUES($1,'pricing','price_recommendation','{}','Provider explanation')`,[tenantId]),e=>e.code==='23514' && e.constraint==='chk_evidence_shape');
    console.log('REPRODUCED 23514/chk_evidence_shape with the original insert shape');
    await db.query("SELECT set_config('app.current_user_id','',false),set_config('app.current_tenant_id','',false)");
    socket=new PGLiteSocketServer({db,host:'127.0.0.1',port:0});await socket.start();
    process.env.DATABASE_URL=`postgresql://ceopro_app@${socket.getServerConn()}/postgres`;
    ({prisma}=await import('../../src/config/database.ts'));
    const {persistPricingRecommendation}=await import('../../src/modules/pricing/repo/pricing.repo.ts');
    const base={tenantId,userId,productId,status:'OK',action:'hold',currentPrice:10,suggestedPrice:10,confidenceScore:0.4,
      explanationText:'  Actual provider explanation.  ',matchedCompetitorCount:2,guardrailClamped:false,marginGuardrailClamped:false};
    for(const [status,explanation] of [['OK',base.explanationText],['OK',null],['OK','   '],['UNKNOWN',null],['UNKNOWN','No comparable competitor prices.']]){
      const input={...base,status,explanationText:explanation,...(status==='UNKNOWN'?{action:null,suggestedPrice:null,confidenceScore:null}: {})};
      const result=await persistPricingRecommendation(input);
      const row=(await prisma.$transaction(async tx=>{
        await tx.$queryRaw`SELECT set_config('app.current_user_id',${userId},true),set_config('app.current_tenant_id',${tenantId},true)`;
        return tx.evidence_records.findUnique({where:{evidence_id:result.evidenceId}});
      }));
      assert.equal(row.category,status==='OK'?'RECOMMENDATION':'UNKNOWN');
      assert.equal(row.source_module,'pricing');assert.equal(row.forecast_id,null);
      assert(row.explanation_text.trim());assert.equal(row.metric_value_json.status,status);
      assert.equal(row.metric_value_json.product_id,productId);
      assert.deepEqual(row.source_record_ids,{product_id:productId});
      if(explanation?.trim()) assert.equal(row.explanation_text,explanation.trim());
      else assert.match(row.explanation_text,/without an explanation/);
      assert.equal(result.outcomeId!==null,status==='OK');
      console.log(`PASS real Prisma ${status}, explanation=${explanation?.trim()?'provided':'missing'}`);
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

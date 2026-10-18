import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { PGLiteSocketServer } from '@electric-sql/pglite-socket';
import { readFileSync,readdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
export async function isolatedDatabase(role, options={}) {
 const db=new PGlite({extensions:{vector,pgcrypto}});
 await db.exec(`CREATE ROLE ceopro_ai_prod_user LOGIN NOSUPERUSER NOBYPASSRLS; CREATE ROLE ceopro_ai_test_user LOGIN NOSUPERUSER NOBYPASSRLS; CREATE ROLE ceopro_ai_test_writer LOGIN NOSUPERUSER NOBYPASSRLS;`);
 const migrations=new URL('../../prisma/migrations/',import.meta.url);
 for(const name of readdirSync(migrations).filter(n=>/^\d/.test(n)).sort())await db.exec(readFileSync(new URL(`${name}/migration.sql`,migrations),'utf8'));
 const socket=new PGLiteSocketServer({db,host:'127.0.0.1',port:0,...options});await socket.start();
 const url=`postgresql://${role}@${socket.getServerConn()}/postgres`;
 return {db,socket,url,async role(name){
  await db.exec(`RESET SESSION AUTHORIZATION; SET SESSION AUTHORIZATION ${name}`);
  if(name!=='postgres'){
    const r=(await db.query('SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).rows[0];
    assert.equal(r.name,name);assert.equal(r.rolsuper,false);assert.equal(r.rolbypassrls,false);
  }
 },async close(){await socket.stop();await db.close();}};
}
export async function tenantFixture(db){
 const tenantId=randomUUID(),userId=randomUUID(),productId=randomUUID();
 await db.query(`INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES($1,'Isolated fixture','JO','JOD')`,[tenantId]);
 await db.query(`INSERT INTO users(user_id,email,password_hash) VALUES($1,$2,'test')`,[userId,`${userId}@example.test`]);
 await db.query(`INSERT INTO tenant_users(tenant_id,user_id,role_key) VALUES($1,$2,'owner')`,[tenantId,userId]);
 const plan=await planFixture(db,tenantId);
 await db.query(`INSERT INTO products(product_id,tenant_id,product_name,current_price,currency) VALUES($1,$2,'{"en":"Tea"}',10,'JOD')`,[productId,tenantId]);
 return {tenantId,userId,productId,...plan};
}
export async function planFixture(db,tenantId,storageLimit=1,extractionLimit=10000){
 const planId=randomUUID(),subscriptionId=randomUUID();
 await db.query(`INSERT INTO plans(id,name,name_ar,price,billing_interval_value,billing_interval_unit) VALUES($1,'Isolated','Isolated',0,1,'month')`,[planId]);
 for(const [code,aggregation,limit] of [['document_storage_mb','max',storageLimit],['document_extraction','sum',extractionLimit],['tracked_products','max',null]]){
  await db.query(`INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type,aggregation_type,reset_cycle) VALUES($1,$1,$1,'limit',$2,$3) ON CONFLICT(feature_code) DO NOTHING`,[code,aggregation,code==='document_extraction'?'billing_period':'lifetime']);
  await db.query(`INSERT INTO plan_features(plan_id,feature_id,limit_value) SELECT $1,feature_id,$2 FROM features WHERE feature_code=$3`,[planId,limit,code]);
 }
 await db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('product_management','Products','Products','boolean') ON CONFLICT(feature_code) DO NOTHING");
 await db.query("INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='product_management'",[planId]);
 await db.exec("INSERT INTO features(feature_code,feature_name,feature_name_ar,feature_type) VALUES('data_integration','Data','Data','boolean') ON CONFLICT(feature_code) DO NOTHING");
 await db.query("INSERT INTO plan_features(plan_id,feature_id) SELECT $1,feature_id FROM features WHERE feature_code='data_integration'",[planId]);
 await db.query(`INSERT INTO subscriptions(id,tenant_id,plan_id,payment_provider,status,current_period_start,current_period_end) VALUES($1,$2,$3,'stripe','active',now()-interval '1 day',now()+interval '29 days')`,[subscriptionId,tenantId,planId]);
 return {planId,subscriptionId};
}

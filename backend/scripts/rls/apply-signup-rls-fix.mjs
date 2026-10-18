import pg from 'pg';
import dotenv from 'dotenv';
import { spawnSync } from 'node:child_process';
import assert from 'node:assert/strict';
dotenv.config({quiet:true});

// Only this child migration process uses the schema administrator. Neither
// backend/.env nor the application's runtime connection is rewritten.
const runtimeUrl=process.env.DATABASE_URL;
const adminUrl=process.env.BOOTSTRAP_DATABASE_URL;
assert(runtimeUrl && adminUrl,'Set DATABASE_URL and BOOTSTRAP_DATABASE_URL in backend/.env');
for(const value of [runtimeUrl,adminUrl]) assert.equal(new URL(value).pathname,'/KEEL_DEV','This local repair launcher is restricted to KEEL_DEV');
const runtime=new pg.Client({connectionString:runtimeUrl,connectionTimeoutMillis:10000});
const admin=new pg.Client({connectionString:adminUrl,connectionTimeoutMillis:10000});
try {
  await runtime.connect();await admin.connect();
  const row=(await runtime.query(`SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user`)).rows[0];
  assert.equal(row.name,'ceopro_app');assert.equal(row.rolsuper,false);assert.equal(row.rolbypassrls,false);
  assert.equal((await admin.query('SELECT current_user AS name')).rows[0].name,'keel_migrator');
  console.log('Verified KEEL_DEV identities: ceopro_app runtime and keel_migrator migration connection');
} catch(error) {
  console.error(`Preflight failed: ${error.code || error.name}: ${error.message}`);
  process.exitCode=1;
} finally {await runtime.end().catch(()=>{});await admin.end().catch(()=>{});}
if(!process.exitCode) {
  const result=spawnSync('npm',['run','prisma:migrate:test'],{
    stdio:'inherit',shell:process.platform==='win32',
    env:{...process.env,DATABASE_URL:adminUrl}
  });
  process.exitCode=result.status ?? 1;
  if(result.error) console.error('Could not start Prisma migration deployment');
  if(process.exitCode===0) console.log('Migration deployment completed; backend/.env and runtime DATABASE_URL remain unchanged');
}

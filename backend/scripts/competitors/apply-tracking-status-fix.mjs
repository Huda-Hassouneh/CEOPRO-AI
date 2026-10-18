import pg from 'pg';
import dotenv from 'dotenv';
import {spawnSync} from 'node:child_process';
import assert from 'node:assert/strict';
dotenv.config({quiet:true});
const runtimeUrl=process.env.DATABASE_URL,adminUrl=process.env.BOOTSTRAP_DATABASE_URL;
assert(runtimeUrl && adminUrl,'Set DATABASE_URL and BOOTSTRAP_DATABASE_URL in backend/.env');
for(const value of [runtimeUrl,adminUrl])assert.equal(new URL(value).pathname,'/KEEL_DEV','Launcher restricted to existing KEEL_DEV');
const endpoint=value=>{const u=new URL(value);return `${u.hostname==='localhost'?'127.0.0.1':u.hostname}:${u.port||'5432'}`;};
assert.equal(endpoint(runtimeUrl),endpoint(adminUrl),'Connections must target the same PostgreSQL server');
const runtime=new pg.Client({connectionString:runtimeUrl,connectionTimeoutMillis:10000});
const admin=new pg.Client({connectionString:adminUrl,connectionTimeoutMillis:10000});
try {
 await runtime.connect();await admin.connect();
 const role=(await runtime.query('SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).rows[0];
 assert.equal(role.name,'ceopro_app');assert.equal(role.rolsuper,false);assert.equal(role.rolbypassrls,false);
 assert.equal((await admin.query('SELECT current_user AS name')).rows[0].name,'keel_migrator');
 console.log('Verified restricted runtime and migration administrator on KEEL_DEV');
}catch(error){console.error(`Preflight failed: ${error.code||error.name}: ${error.message}`);process.exitCode=1;}
finally{await runtime.end().catch(()=>{});await admin.end().catch(()=>{});}
if(!process.exitCode){
 const result=spawnSync('npm',['run','prisma:migrate:test'],{stdio:'inherit',shell:process.platform==='win32',env:{...process.env,DATABASE_URL:adminUrl}});
 process.exitCode=result.status??1;
 if(result.error)console.error('Could not start Prisma migration deployment');
 if(!process.exitCode)console.log('Competitor tracking status fix applied; runtime .env unchanged');
}

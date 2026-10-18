import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {readFileSync,existsSync} from 'node:fs';
import {parseEnv} from 'node:util';
import {spawnSync} from 'node:child_process';
const root=fileURLToPath(new URL('../',import.meta.url));
const require=createRequire(new URL('../backend/package.json',import.meta.url));
const pg=require('pg');
const file=new URL('../backend/.env',import.meta.url);
const env={...(existsSync(file)?parseEnv(readFileSync(file,'utf8')):{}),...process.env};
const action=process.argv[2];
if(!['init','migrate','roles'].includes(action))throw Error('Use init, migrate or roles');
const url=env.BOOTSTRAP_DATABASE_URL;
if(!url||url.includes('REPLACE_'))throw Error('Configure backend/.env BOOTSTRAP_DATABASE_URL for the development database');
const target=new URL(url);
if(env.NODE_ENV==='production'||!/DEV|TEST/i.test(decodeURIComponent(target.pathname)))throw Error('This helper is restricted to development/test databases');
const client=new pg.Client({connectionString:url,connectionTimeoutMillis:8000});
try{
 await client.connect();
 if(action==='roles'){
  const settings=[['ceopro_app','DATABASE_URL'],['ceopro_market_dispatcher','MARKET_DISPATCHER_DATABASE_URL'],['ceopro_ingestion_worker','INGESTION_WORKER_DATABASE_URL'],['ceopro_notification_worker','NOTIFICATION_WORKER_DATABASE_URL']];
  const changes=[];
  for(const [role,key] of settings){
   if(!env[key]||env[key].includes('REPLACE_'))throw Error(`Configure ${key} before provisioning passwords`);
   const login=new URL(env[key]);
   const host=u=>(u.hostname==='localhost'?'127.0.0.1':u.hostname)+':'+(u.port||'5432')+u.pathname;
   if(host(login)!==host(target)||decodeURIComponent(login.username)!==role||!login.password)throw Error(`${key} must use ${role} on the configured development database`);
   const result=await client.query('SELECT rolsuper,rolbypassrls,rolcreaterole,rolcreatedb,rolreplication FROM pg_roles WHERE rolname=$1',[role]);
   if(!result.rows.length||Object.values(result.rows[0]).some(Boolean))throw Error(`Role ${role} is missing or unsafe; inspect migrations and role grants`);
   changes.push([role,decodeURIComponent(login.password)]);
  }
  await client.query('BEGIN');
  for(const [role,password] of changes)await client.query(`ALTER ROLE ${pg.escapeIdentifier(role)} LOGIN PASSWORD ${pg.escapeLiteral(password)}`);
  await client.query('COMMIT');
  console.log('Development runtime passwords aligned; existing privilege/RLS grants retained.');
 }else{
  if(action==='init'){
   const tables=await client.query("SELECT tablename FROM pg_tables WHERE schemaname='public'");
   if(tables.rowCount)throw Error('Database is not empty; db:init refused. Use db:migrate for an existing Prisma-managed database.');
  }
  // Historical migrations reference these roles explicitly. No passwords are
  // assigned: the aliases cannot authenticate over password-based connections.
  await client.query(`DO $$ BEGIN
   IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_ai_prod_user') THEN CREATE ROLE ceopro_ai_prod_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION; END IF;
   IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_ai_test_user') THEN CREATE ROLE ceopro_ai_test_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION; END IF;
   IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='ceopro_ai_test_writer') THEN CREATE ROLE ceopro_ai_test_writer LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION; END IF;
  END $$;`);
  await client.end();
  const result=spawnSync(process.platform==='win32'?'npm.cmd':'npm',['run','prisma:migrate:test'],{cwd:new URL('../backend',import.meta.url),stdio:'inherit',shell:process.platform==='win32',env:{...env,DATABASE_URL:url}});
  if(result.error||result.status!==0)throw Error('Prisma deployment failed; inspect its output. No reset was attempted.');
  console.log('Prisma migrations deployed. Runtime DATABASE_URL was not changed. Run db:roles after configuring runtime URLs.');
 }
}catch(error){
 await client.query('ROLLBACK').catch(()=>{});
 // Never print a PostgreSQL connection URL or password.
 console.error(error.code?`Database setup failed (${error.code}); check the target and privileges.`:error.message);
 process.exitCode=1;
}finally{await client.end().catch(()=>{});}

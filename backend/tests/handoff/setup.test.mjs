import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,readdirSync} from 'node:fs';
import {spawn} from 'node:child_process';
import {PGlite} from '@electric-sql/pglite';
import {vector} from '@electric-sql/pglite/vector';
import {pgcrypto} from '@electric-sql/pglite/contrib/pgcrypto';
import {PGLiteSocketServer} from '@electric-sql/pglite-socket';
// Resolve from tests/handoff to repository root, independent of test cwd.
const helper=new URL('../../../scripts/development-database.mjs',import.meta.url);
function run(action,env){return new Promise((resolve,reject)=>{
 const p=spawn(process.execPath,[helper.pathname,action],{env:{...process.env,...env},stdio:['ignore','pipe','pipe']});
 let output='';p.stdout.on('data',v=>output+=v);p.stderr.on('data',v=>output+=v);p.once('error',reject);p.once('exit',code=>resolve({code,output}));
});}
test('development helper rejects production before connecting and never exposes credentials',async()=>{
 const secret='not-a-real-db-password';
 const result=await run('migrate',{NODE_ENV:'production',BOOTSTRAP_DATABASE_URL:`postgresql://admin:${secret}@127.0.0.1:1/KEEL_DEV`});
 assert.notEqual(result.code,0);assert.match(result.output,/restricted to development\/test/);assert.ok(!result.output.includes(secret));
});
test('fresh compatibility roles support every migration; existing DB init refuses and password alignment retains restricted privileges',async()=>{
 const db=new PGlite({extensions:{vector,pgcrypto}});let server;
 try{
  // Exercise the exact compatibility-role block in the new helper, not alternate test grants.
  const source=readFileSync(helper,'utf8');
  const setup=source.match(/await client\.query\(`(DO \$\$ BEGIN[\s\S]*?END \$\$;)`\)/)?.[1];assert.ok(setup);
  await db.exec(setup);
  const migrations=new URL('../../prisma/migrations/',import.meta.url);
  for(const name of readdirSync(migrations).filter(n=>/^\d/.test(n)).sort())await db.exec(readFileSync(new URL(`${name}/migration.sql`,migrations),'utf8'));
  server=new PGLiteSocketServer({db,host:'127.0.0.1',port:0,maxConnections:4});await server.start();
  const base=`postgresql://postgres@${server.getServerConn()}/KEEL_TEST`;
  const env={NODE_ENV:'development',BOOTSTRAP_DATABASE_URL:base};
  const roles=['ceopro_app','ceopro_market_dispatcher','ceopro_ingestion_worker','ceopro_notification_worker'];
  for(const [i,key] of ['DATABASE_URL','MARKET_DISPATCHER_DATABASE_URL','INGESTION_WORKER_DATABASE_URL','NOTIFICATION_WORKER_DATABASE_URL'].entries())env[key]=`postgresql://${roles[i]}:isolated-${i}-password@${server.getServerConn()}/KEEL_TEST`;
  let result=await run('init',env);assert.notEqual(result.code,0);assert.match(result.output,/not empty/);
  result=await run('roles',env);assert.equal(result.code,0,result.output);assert.match(result.output,/privilege\/RLS grants retained/);
  const actual=(await db.query('SELECT rolname,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=ANY($1)',[roles])).rows;
  assert.equal(actual.length,4);for(const r of actual)assert.equal(r.rolsuper||r.rolbypassrls||r.rolcreatedb||r.rolcreaterole,false);
  assert.equal((await db.query("SELECT relrowsecurity FROM pg_class WHERE oid='users'::regclass")).rows[0].relrowsecurity,true);
  const before=(await db.query("SELECT count(*)::int AS n FROM pg_tables WHERE schemaname='public'")).rows[0].n;
  result=await run('roles',{...env,DATABASE_URL:env.DATABASE_URL.replace('ceopro_app','postgres')});assert.notEqual(result.code,0);
  assert.equal((await db.query("SELECT count(*)::int AS n FROM pg_tables WHERE schemaname='public'")).rows[0].n,before);
 }finally{if(server)await server.stop();await db.close();}
});

import pg from 'pg';
import assert from 'node:assert/strict';
import { runRlsScenarios } from './rls-scenarios.mjs';
import dotenv from 'dotenv';
dotenv.config({ quiet: true });

// No migrations, roles, policies, grants, or permanent test data are changed here.
// The administrator connection creates rollback-only fixtures; every permission
// assertion switches to the genuine ceopro_app role and verifies its identity.
const adminUrl = process.env.KEEL_RLS_TEST_ADMIN_URL || process.env.BOOTSTRAP_DATABASE_URL;
const runtimeUrl = process.env.KEEL_RLS_TEST_APP_URL || process.env.DATABASE_URL;
if (!adminUrl || !runtimeUrl || process.env.KEEL_RLS_TEST_ACK !== 'KEEL_DEV') {
  console.error('BLOCKED: configure BOOTSTRAP_DATABASE_URL and DATABASE_URL in backend/.env (or KEEL_RLS_TEST_*_URL overrides), and set KEEL_RLS_TEST_ACK=KEEL_DEV.');
  process.exit(2);
}
for(const value of [adminUrl,runtimeUrl]) {
  const url = new URL(value);
  assert.equal(decodeURIComponent(url.pathname.slice(1)),'KEEL_DEV','This runner is restricted to KEEL_DEV');
}
const app = new pg.Client({ connectionString: runtimeUrl, connectionTimeoutMillis: 10000 });
const admin = new pg.Client({ connectionString: adminUrl, connectionTimeoutMillis: 10000 });
try {
  await app.connect();
  const role=(await app.query(`SELECT current_user AS name,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user`)).rows[0];
  assert.equal(role.name,'ceopro_app');assert.equal(role.rolsuper,false);assert.equal(role.rolbypassrls,false);
  await app.query('BEGIN');
  await app.query(`SELECT set_config('app.auth_email','missing-'||gen_random_uuid()::text||'@rls-regression.example',true)`);
  for(const table of ['users','tenant_users','companies']) await app.query(`SELECT * FROM public.${table} LIMIT 0`);
  await app.query('SAVEPOINT cannot_switch');
  await assert.rejects(() => app.query('SET LOCAL ROLE ceopro_platform_overview_reader'),e=>e.code==='42501');
  await app.query('ROLLBACK TO SAVEPOINT cannot_switch');
  await app.query('ROLLBACK');
  console.log('PASS direct ceopro_app connection: anonymous auth/membership/company reads do not recurse');
  await admin.connect();
  assert.equal((await admin.query('SELECT current_database() AS name')).rows[0].name,'KEEL_DEV');
  assert.equal((await admin.query('SELECT to_regprocedure($1) AS function',['public.platform_admin_can_read_customer_user(uuid)'])).rows[0].function !== null,true,'Apply the forward migration first');
  console.log(`PASS ${await runRlsScenarios(admin)} database workflow groups; fixtures rolled back`);
} catch(error) {
  // Print the SQLSTATE and safe message, never connection strings/passwords.
  console.error(`FAIL ${error.code || error.name}: ${error.message}`);
  process.exitCode=1;
} finally {
  await app.query('ROLLBACK').catch(()=>{});
  await admin.query('ROLLBACK').catch(()=>{});
  await app.end().catch(()=>{});await admin.end().catch(()=>{});
}

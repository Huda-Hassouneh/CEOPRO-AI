import assert from 'node:assert/strict';
import test from 'node:test';
import { readdirSync, readFileSync } from 'node:fs';
import { PGlite } from '@electric-sql/pglite';
import { vector } from '@electric-sql/pglite/vector';
import { pgcrypto } from '@electric-sql/pglite/contrib/pgcrypto';
import { runRlsScenarios } from './rls-scenarios.mjs';
import { runAuthRuntimeScenarios } from './auth-runtime-scenarios.mjs';

const repair = '20261014000000_break_platform_admin_rls_cycles';
const migrations = new URL('../../prisma/migrations/', import.meta.url);
const readMigration = name => readFileSync(new URL(`${name}/migration.sql`, migrations), 'utf8');

test('actual migration history reproduces 42P17; forward migration repairs restricted-role workflows', async () => {
  const db = new PGlite({ extensions: { vector, pgcrypto } });
  try {
    await db.exec(`CREATE ROLE ceopro_ai_prod_user LOGIN NOSUPERUSER NOBYPASSRLS;
      CREATE ROLE ceopro_ai_test_user LOGIN NOSUPERUSER NOBYPASSRLS;
      CREATE ROLE ceopro_ai_test_writer LOGIN NOSUPERUSER NOBYPASSRLS;`);
    const history = readdirSync(migrations).filter(n => /^\d/.test(n) && n < repair).sort();
    for (const name of history) await db.exec(readMigration(name));
    console.log(`Replayed ${history.length} unchanged migrations; ${(await db.query('SELECT version() AS version')).rows[0].version}`);
    await db.exec(`SET ROLE ceopro_app; SELECT set_config('app.auth_email','absent@rls-regression.example',false)`);
    assert.equal((await db.query('SELECT current_user AS role')).rows[0].role,'ceopro_app');
    for (const table of ['users','tenant_users','companies']) {
      await assert.rejects(() => db.query(`SELECT * FROM public.${table} LIMIT 1`), e => e.code === '42P17');
      console.log(`REPRODUCED 42P17 on ${table} before repair`);
    }
    await db.exec('RESET ROLE');
    await db.exec(readMigration(repair));
    // Retryability matters for manually applied/reconciled development databases.
    await db.exec(readMigration(repair));
    const count = await runRlsScenarios(db);
    assert.equal(count,13);
    assert.equal((await db.query(`SELECT count(*)::int AS count FROM public.users WHERE email LIKE '%@rls-regression.example'`)).rows[0].count,0);
    console.log('Fixture transaction rolled back; no test accounts retained');
    await runAuthRuntimeScenarios(db);
  } finally { await db.close(); }
});

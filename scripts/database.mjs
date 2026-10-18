import { createRequire } from 'node:module';
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseEnv } from 'node:util';
const require = createRequire(new URL('../backend/package.json', import.meta.url));
const { Client } = require('pg');
const readEnv = folder => {
  const file = fileURLToPath(new URL(`../${folder}/.env`, import.meta.url));
  return existsSync(file) ? parseEnv(readFileSync(file, 'utf8')) : {};
};
const env = { ...readEnv('backend'), ...process.env };
const action = process.argv[2] || 'check';
if (action === 'init') { console.error('Use npm run db:init; Prisma owns the complete baseline and migration history.'); process.exit(1); }
const url = action === 'init' ? env.BOOTSTRAP_DATABASE_URL : env.DATABASE_URL;
if (!url || url.includes('REPLACE_')) {
  console.error(`Fill ${action === 'init' ? 'BOOTSTRAP_DATABASE_URL' : 'DATABASE_URL'} locally first.`); process.exit(1);
}
const db = new Client({ connectionString: url, connectionTimeoutMillis: 8000 });
try {
  await db.connect();
  if (action === 'init') {
    const existing = await db.query("SELECT tablename FROM pg_tables WHERE schemaname='public'");
    if (existing.rowCount) throw new Error('Database is not empty. Initialization was refused; preserve its existing migration history.');
    await db.query('BEGIN');
    await db.query(readFileSync(new URL('../backend/prisma/base-schema.sql', import.meta.url), 'utf8'));
    await db.query('COMMIT');
    console.log('Base schema initialized. No tenant/demo data added. Next apply Node Prisma migrations with the schema administrator.');
  } else if (action === 'check') {
    const required = {
      companies: ['tenant_id','platform_status','latitude','longitude','search_scope_level'],
      subscriptions: ['tenant_id','status','plan_id'],
      plan_features: ['plan_id','metadata'],
      products: ['product_id','tenant_id','sku','version'],
      tenant_competitors: ['tenant_id','global_competitor_id','is_tracked','distance_km'],
      competitor_product_mappings: ['tenant_id','source_id','comparison_confirmed','tracking_paused'],
      data_sources: ['source_id','tenant_id','policy_status','collector_config','sync_frequency_minutes'],
      scraping_cost_ledger: ['tenant_id','mapping_id','cost_amount'],
      company_target_markets: ['tenant_id','market_type','country_code','region_name'],
      market_tracking_outbox: ['event_id','tenant_id','kind','status'],
    };
    const columns = await db.query("SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'");
    const known = new Set(columns.rows.map(row => `${row.table_name}.${row.column_name}`));
    const missing = Object.entries(required).flatMap(([table,names]) => names.filter(name => !known.has(`${table}.${name}`)).map(name => `${table}.${name}`));
    const identity = await db.query('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user');
    const unsafeRole = identity.rows[0]?.rolsuper || identity.rows[0]?.rolbypassrls;
    if (missing.length) console.error(`Missing schema: ${missing.join(', ')}`);
    if (unsafeRole) console.error('Application DATABASE_URL uses a role that bypasses RLS. Configure its restricted login.');
    const ai = readEnv('ai');
    let mismatch = false;
    const pairs = [['MARKET_DISCOVERY_STREAM_KEY','DISCOVERY_STREAM_KEY','market.discovery.requested'],['MARKET_SCRAPER_STREAM_KEY','SCRAPER_STREAM_KEY','market.scrape.requested']];
    for (const [nodeKey, aiKey, fallback] of pairs) {
      if ((env[nodeKey] || fallback) !== (ai[aiKey] || fallback)) { mismatch = true; console.error(`Stream configuration differs: ${nodeKey}/${aiKey}`); }
    }
    const sameEndpoint = (a,b) => { try { const x=new URL(a),y=new URL(b); return x.hostname===y.hostname && (x.port||'5432')===(y.port||'5432') && x.pathname===y.pathname; } catch { return false; } };
    if (!sameEndpoint(env.DATABASE_URL, ai.SCRAPER_DATABASE_URL || ai.DATABASE_URL)) { mismatch = true; console.error('Python workers do not point to the same PostgreSQL endpoint/database as Node.'); }
    if (!env.MARKET_REDIS_URL || env.MARKET_REDIS_URL !== ai.REDIS_URL) { mismatch = true; console.error('Node/Python Redis URLs differ or are missing.'); }
    if (!ai.SCRAPER_ACTOR_USER_ID || ai.SCRAPER_ACTOR_USER_ID.includes('REPLACE_') || ai.SCRAPER_ACTOR_USER_ID === '00000000-0000-0000-0000-000000000000') { mismatch = true; console.error('Set a real authorized SCRAPER_ACTOR_USER_ID; standalone nil-actor configuration is not used.'); }
    if (env.SCRAPER_ACTOR_USER_ID !== ai.SCRAPER_ACTOR_USER_ID ||
        !sameEndpoint(env.SCRAPER_DATABASE_URL, ai.SCRAPER_DATABASE_URL || ai.DATABASE_URL)) {
      mismatch = true; console.error('The Node cost gate and Python workers must use the same scraper actor and database.');
    }
    if (missing.length || unsafeRole || mismatch) process.exitCode=1;
    else console.log('Schema and configured database/stream endpoints align. Provider calls, worker privileges, Redis connectivity, and live collection still need verification.');
  } else throw new Error('Use init or check.');
} catch (error) {
  try { await db.query('ROLLBACK'); } catch {}
  // Connection strings and raw provider errors are not printed.
  console.error(error.message?.includes('refused') || error.message?.startsWith('Use ') ? error.message : 'Database check/setup failed. Check local credentials, privileges, and schema.');
  process.exitCode=1;
} finally { await db.end(); }

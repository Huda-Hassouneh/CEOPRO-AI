"""Fresh/baseline-upgrade/repeat proof on uniquely named disposable databases.
Uses the repository migration runner; never rewrites history or drops resources.
Only the already-owned local keel_test_admin cluster is accepted. Credentials
come from environment, never command arguments or result files.
"""
import contextlib,importlib.util,json,logging,os,subprocess,uuid
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit,quote
import psycopg2
from psycopg2 import sql

BASE='a00669dd8500dcce7dba9d94e2fbfac5a22d8808'
BACKEND=Path(__file__).resolve().parents[1];REPO=BACKEND.parent

@contextlib.contextmanager
def migration_log(path):
    # Logging handlers capture their stream when initialized, so redirect them too.
    handlers=[h for h in logging.getLogger().handlers if isinstance(h,logging.StreamHandler)]
    streams=[h.stream for h in handlers]
    with path.open('w',encoding='utf-8') as log:
        try:
            for handler in handlers:handler.setStream(log)
            with contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):yield
        finally:
            for handler,stream in zip(handlers,streams):handler.setStream(stream)

def main():
    if os.getenv('KEEL_ALLOW_DISPOSABLE_MIGRATION_TESTS')!='YES':raise RuntimeError('Explicit disposable migration verification flag required')
    dsn=os.environ['KEEL_DISPOSABLE_CLUSTER_DSN'];parts=urlsplit(dsn)
    if parts.hostname!='127.0.0.1' or parts.port!=60433 or parts.username!='keel_test_admin' or parts.path!='/postgres' or parts.query:raise RuntimeError('Existing owned disposable cluster identity required')
    out=Path(os.environ['KEEL_MIGRATION_EVIDENCE_DIR']);out.mkdir(parents=True,exist_ok=True)
    ledger_path=out/'migration-resources.json'
    if ledger_path.exists():raise RuntimeError('Evidence directory already owns a run; reconcile its ledger before rerunning')
    run=uuid.uuid4().hex[:12];ledger={'run_id':run,'host':'127.0.0.1','port':60433,'baseline':BASE,'source_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'databases':{}}
    def save():ledger_path.write_text(json.dumps(ledger,indent=2)+'\n',encoding='utf-8')
    save()
    spec=importlib.util.spec_from_file_location('remaining_migration_runner',BACKEND/'scripts/apply_migrations.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    current=runner.MIGRATIONS_DIR
    total=len(list(current.glob('*.sql')));new_count=total-123
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'--','backend/src/infrastructure/database/migrations'],cwd=REPO,text=True).splitlines()
    baseline=out/'original-sequence';baseline.mkdir()
    for name in names:
        if not name.endswith('.sql'):continue
        raw=subprocess.check_output(['git','show',BASE+':'+name],cwd=REPO)
        if raw!=(REPO/name).read_bytes():raise RuntimeError('Historical migration changed: '+Path(name).name)
        (baseline/Path(name).name).write_bytes(raw)
    assert len(list(baseline.glob('*.sql')))==123
    tables=['products','keel_file_upload_requests','keel_structured_import_posts','keel_provider_privacy_requests','keel_pricing_request_results','keel_provider_order_posts','keel_provider_stock_posts','keel_provider_stock_scan_members','keel_provider_promotion_decisions']
    results={}
    for mode in ['fresh','upgrade']:
        name='keel_billing_test_'+run+'_'+mode
        with contextlib.closing(psycopg2.connect(dsn)) as admin:
            admin.autocommit=True
            with admin.cursor() as c:c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        ledger['databases'][mode]={'name':name,'created_by_this_run':True};save()
        target=urlunsplit(parts._replace(path='/'+name));os.environ['DATABASE_URL']=target
        with contextlib.closing(psycopg2.connect(target)) as conn:
            with migration_log(out/(mode+'-migrations.log')):
                if mode=='upgrade':
                    runner.MIGRATIONS_DIR=baseline;initial=runner.run(conn);assert len(initial)==123
                    tenant=str(uuid.uuid4());product=str(uuid.uuid4());invoice=str(uuid.uuid4())
                    with conn.cursor() as c:
                        c.execute("INSERT INTO companies(tenant_id,business_name,country_code,primary_currency) VALUES(%s,'Synthetic upgrade preservation','JO','JOD')",(tenant,))
                        c.execute("INSERT INTO products(product_id,tenant_id,product_name,current_price,currency,metadata) VALUES(%s,%s,'{\"en\":\"Legacy preserved\"}',12,'JOD','{\"legacy\":true}')",(product,tenant))
                        c.execute('INSERT INTO inventory(tenant_id,product_id,stock_quantity) VALUES(%s,%s,6)',(tenant,product))
                        c.execute("INSERT INTO invoices(invoice_id,tenant_id,invoice_number,subtotal,tax_amount,total_amount,currency,payment_status) VALUES(%s,%s,'SYNTHETIC-LEGACY-UPGRADE',24,1,25,'JOD','PAID')",(invoice,tenant))
                        c.execute('INSERT INTO invoice_items(tenant_id,invoice_id,product_id,quantity,unit_price,total_price) VALUES(%s,%s,%s,2,12,24)',(tenant,invoice,product))
                    conn.commit()
                runner.MIGRATIONS_DIR=current;applied=runner.run(conn);assert len(applied)==(total if mode=='fresh' else new_count)
                assert runner.run(conn)==[]
            with conn.cursor() as c:
                c.execute('SELECT count(*) FROM schema_migrations');assert c.fetchone()==(total,)
                if mode=='upgrade':
                    c.execute('SELECT product_name,current_price,metadata,sku,version FROM products WHERE tenant_id=%s AND product_id=%s',(tenant,product));row=c.fetchone();assert row[0]=={'en':'Legacy preserved'} and row[1]==12 and row[2]=={'legacy':True} and row[3] is None and row[4]==1
                    c.execute('SELECT stock_quantity FROM inventory WHERE tenant_id=%s AND product_id=%s',(tenant,product));assert c.fetchone()==(6,)
                    c.execute('SELECT total_amount,payment_status FROM invoices WHERE tenant_id=%s AND invoice_id=%s',(tenant,invoice));assert c.fetchone()==(25,'PAID')
                    c.execute('SELECT quantity,unit_price,total_price,rounding_adjustment FROM invoice_items WHERE tenant_id=%s AND invoice_id=%s',(tenant,invoice));assert c.fetchone()==(2,12,24,0)
                c.execute("SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)",(tables,));flags=c.fetchall();assert len(flags)==len(tables) and all(x[1] and x[2] for x in flags)
                c.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname='ceopro_app'");assert c.fetchone()==(False,False)
            password=os.environ['APP_DB_PASSWORD'];app_parts=parts._replace(netloc='ceopro_app:'+quote(password,safe='')+'@127.0.0.1:60433',path='/'+name)
            with contextlib.closing(psycopg2.connect(urlunsplit(app_parts))) as restricted,restricted.cursor() as c:
                c.execute('SELECT current_user');assert c.fetchone()==('ceopro_app',)
                for table in ['keel_provider_order_posts','keel_provider_stock_posts','keel_provider_stock_scan_members','keel_provider_promotion_decisions']:
                    c.execute("SELECT has_table_privilege(current_user,%s,'UPDATE'),has_table_privilege(current_user,%s,'DELETE')",(table,table));assert c.fetchone()==(False,False)
                for table in tables:
                    c.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)));assert c.fetchone()==(0,)
            results[mode]={'status':'PASS','total_migrations':total,'newly_applied':len(applied),'repeat_newly_applied':0,'restricted_password_login':'PASS','force_rls':tables,'legacy_data_preserved':mode=='upgrade','legacy_paid_invoice_preserved':mode=='upgrade','immutable_receipt_permissions':'PASS'}
        ledger['databases'][mode]['verified']=True;save()
    (out/'migration-results.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    print(f'PASS: fresh{total}; original123 + upgrade{new_count}; repeat0; restricted password login, FORCE RLS and legacy product/stock preservation. Resources retained in scoped ledger.')

if __name__=='__main__':main()

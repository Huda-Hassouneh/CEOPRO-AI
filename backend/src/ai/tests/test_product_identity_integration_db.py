"""Source-backed identity integration over canonical products and restricted RLS."""
import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest,psycopg2
from src.ai import db
from src.ai.routers.products import create_product,update_product,list_products
from src.ai.extraction.product_identity import match_reference,normalize_sku,resolve_reference
from src.ai.tests.test_products_integration_db import seeded_tenants

def product(c,t,u,name,sku):return create_product(c,t,u,{'en':name},None,None,None,10,None,'JOD',sku=sku)

@pytest.mark.parametrize('value',[' bad space','-bad','x'*101,'<script>','عربي'])
def test_sku_validation(value):
    with pytest.raises(ValueError):normalize_sku(value)

def test_reference_intersection_never_prefers_one_conflicting_identifier():
    a,b=str(uuid4()),str(uuid4());rows=[{'product_id':a,'product_name':{'en':'Same'},'sku':'A','metadata':{}},{'product_id':b,'product_name':{'en':'Same'},'sku':'B','metadata':{}}]
    assert match_reference({'product_name':'same'},rows)['status']=='ambiguous'
    assert match_reference({'sku':'a','product_name':'same'},rows)['product_id']==a
    assert match_reference({'product_id':a,'sku':'B'},rows)['status']=='conflict'
    assert match_reference({'sku':'missing','product_name':'same'},rows)['status']=='conflict'
    assert match_reference({'sku':'missing'},rows)['status']=='missing'

def test_tenant_scoped_sku_uniqueness_aliases_and_conflicts(seeded_tenants):
    ts,us=seeded_tenants;c=db.app_role_connection(ts[0],us[0]);other=db.app_role_connection(ts[1],us[1])
    try:
        a=product(c,ts[0],us[0],'Tea','TEA.1');c.commit();assert a['sku']=='TEA.1' and a['version']==1
        found=list_products(c,ts[0],25,0,search='tea.1');assert found['total']==1 and found['products'][0]['sku']=='TEA.1'
        product(other,ts[1],us[1],'Other Tea','tea.1');other.commit()
        with pytest.raises(psycopg2.errors.UniqueViolation):product(c,ts[0],us[0],'Duplicate','tea.1')
        c.rollback();b=product(c,ts[0],us[0],'Other','B');c.commit()
        assert resolve_reference(c,ts[0],{'product_id':b['product_id'],'sku':'TEA.1'})['status']=='conflict'
        assert resolve_reference(c,ts[0],{'product_name':'Other Tea'})['status']=='missing'
        update_product(c,ts[0],us[0],a['product_id'],{'product_name':{'en':'Renamed Tea'}});c.commit()
        assert resolve_reference(c,ts[0],{'sku':'tea.1','product_name':'Tea'})['product_id']==a['product_id']
        with c.cursor() as q:q.execute('SELECT current_user');assert q.fetchone()[0]=='ceopro_app'
    finally:c.close();other.close()

def test_last_sku_slot_has_one_committed_winner(seeded_tenants):
    ts,us=seeded_tenants;barrier=threading.Barrier(2)
    def write(i):
        c=db.app_role_connection(ts[0],us[0])
        try:
            barrier.wait();p=product(c,ts[0],us[0],f'Concurrent {i}','SAME');c.commit();return p['product_id']
        except psycopg2.errors.UniqueViolation:c.rollback();return 'conflict'
        finally:c.close()
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(write,[1,2]))
    assert result.count('conflict')==1


def test_original_nfkc_whitespace_lowercase_reference_rules():
    pid=str(uuid4());rows=[{'product_id':pid,'product_name':{'en':'Ｆｕｌｌ  Width'},'sku':None,'metadata':{'import_name_aliases':'invalid legacy metadata'}}]
    assert match_reference({'product_name':'full width'},rows)['product_id']==pid
    rows[0]['product_name']={'en':'Straße'}
    assert match_reference({'product_name':'STRASSE'},rows)['status']=='missing'
    with pytest.raises(ValueError):normalize_sku(True)

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from src.ai.market_inputs import market_structure


def test_manual_and_scraped_prices_have_distinct_nonverified_provenance():
    conn=MagicMock()
    cur=conn.cursor.return_value.__enter__.return_value
    observed=datetime.now(timezone.utc)
    cur.fetchall.side_effect=[
        [('DIRECT',None,1,[],True,None,None),('DIRECT',None,1,[],True,'prices_found','PRODUCT_SEARCH')],
        [('Oil',Decimal(9.5),'JOD',Decimal(9),'JOD','Manual rival','https://manual.example',observed,'manual_or_unrecorded'),
         ('Oil',Decimal(9.5),'JOD',Decimal(10),'JOD','Scraped rival','https://scraped.example',observed,'scraped')]]
    result=market_structure.build(conn,'tenant')
    assert result['registration']=={'manual_or_unrecorded':1,'automatically_discovered':1}
    prices=result['product_prices'][0]['prices']
    assert [x['provenance'] for x in prices]==['manual_or_unrecorded','scraped']
    assert all(x['provider_verified'] is False for x in prices)
    # Source matching must remain tenant-scoped; a URL or ALLOWED flag isn't verification.
    query=cur.execute.call_args_list[1].args[0]
    assert 'mo.tenant_id=cpm.tenant_id' in query and 'e.tenant_id=cpm.tenant_id' in query

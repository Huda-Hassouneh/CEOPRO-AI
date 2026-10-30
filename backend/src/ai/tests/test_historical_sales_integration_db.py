"""Historical scope includes old invoices and never another tenant's sales."""
from datetime import datetime, timedelta, timezone

from src.ai.rag.structured_context import build_historical_sales_lines
from src.ai.tests.test_dashboard_reports_integration_db import (
    conn, _insert_company, _insert_product, _insert_invoice, pytestmark,
)


def test_all_history_ranks_old_sales_and_keeps_tenants_separate(conn):
    tenant=_insert_company(conn)
    other=_insert_company(conn)
    old=_insert_product(conn,tenant,'Historical winner')
    new=_insert_product(conn,tenant,'Recent seller')
    foreign=_insert_product(conn,other,'Foreign secret')
    now=datetime.now(timezone.utc)
    _insert_invoice(conn,tenant,old,10,100,now-timedelta(days=400))
    _insert_invoice(conn,tenant,new,1,50,now)
    _insert_invoice(conn,other,foreign,1000,1000,now)
    text='\n'.join(build_historical_sales_lines(conn,tenant))
    assert '1050 JOD' in text and '1000 JOD' in text
    assert text.index('Historical winner')<text.index('Recent seller')
    assert 'Foreign secret' not in text and '1,000,000' not in text

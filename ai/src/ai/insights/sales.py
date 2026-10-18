"""A declared per-product sales source; never sum overlapping ledgers.

For the entire requested comparison window, use recorded transactions when
present for that product, otherwise paid invoice lines. The source is exposed
in evidence. This is not a claim that invoice and transaction IDs are linked.
"""
from datetime import datetime, timezone

SALES_CTE = """
WITH transaction_products AS (
 SELECT DISTINCT product_id FROM transactions
 WHERE tenant_id=%(tenant_id)s AND transaction_date >= %(since)s
   AND transaction_date < %(until)s AND quantity_sold>0
), sales AS (
 SELECT product_id,transaction_date AS at,quantity_sold::numeric AS units,
        transaction_id AS record_id,'transactions'::text AS source
 FROM transactions WHERE tenant_id=%(tenant_id)s
   AND transaction_date >= %(since)s AND transaction_date < %(until)s AND quantity_sold>0
 UNION ALL
 SELECT ii.product_id,i.issue_date,ii.quantity::numeric,ii.invoice_item_id,'paid_invoice_items'
 FROM invoice_items ii JOIN invoices i ON i.tenant_id=ii.tenant_id AND i.invoice_id=ii.invoice_id
 WHERE ii.tenant_id=%(tenant_id)s AND i.payment_status='PAID'
   AND i.issue_date >= %(since)s AND i.issue_date < %(until)s AND ii.quantity>0
   AND NOT EXISTS(SELECT 1 FROM transaction_products tp WHERE tp.product_id=ii.product_id)
)
"""

def trends(conn, tenant_id, recent_start, prior_start, until=None):
    until = until or datetime.now(timezone.utc)
    with conn.cursor() as cursor:
        cursor.execute(SALES_CTE + """
          SELECT product_id,SUM(units) FILTER(WHERE at >= %(recent_start)s),
                 SUM(units) FILTER(WHERE at < %(recent_start)s),MAX(source),COUNT(*),MAX(at),
                 (array_agg(record_id ORDER BY at DESC,record_id DESC))[1:20]
          FROM sales GROUP BY product_id;
        """, {"tenant_id":tenant_id,"since":prior_start,"recent_start":recent_start,"until":until})
        rows=cursor.fetchall()
    return {str(pid): {"recent_units":float(recent or 0),
            "trend_pct":((float(recent or 0)-float(prior))/float(prior)*100) if prior and float(prior)>0 else None,
            "prior_units":float(prior or 0),"source":source,"record_count":int(count),
            "latest_at":latest.isoformat() if latest else None,"sample_record_ids":[str(i) for i in ids],
            "from":prior_start.isoformat(),"recent_from":recent_start.isoformat(),"until":until.isoformat(),
            "selection":"transactions_preferred_per_product_for_entire_window"}
            for pid,recent,prior,source,count,latest,ids in rows}

def daily(conn,tenant_id,since,until=None):
    with conn.cursor() as cursor:
        cursor.execute(SALES_CTE+"SELECT product_id,at::date,SUM(units) FROM sales GROUP BY product_id,at::date;",
                       {"tenant_id":tenant_id,"since":since,"until":until or datetime.now(timezone.utc)})
        result={}
        for pid,day,units in cursor.fetchall():result.setdefault(str(pid),{})[day]=float(units)
    return result

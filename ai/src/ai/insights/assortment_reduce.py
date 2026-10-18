"""Review excess stock only against a complete 30-target-day forecast.
A single demand_forecasts row is a target-day value, never a 30-day total.
"""
from typing import List
from src.ai.insights.cross_signal import Insight
REDUCE_CANDIDATE_CONFIDENCE=.5

def detect_reduce_candidate_insights(conn,tenant_id:str,max_insights:int=1)->List[Insight]:
    with conn.cursor() as c:
        c.execute("""WITH daily AS (
          SELECT DISTINCT ON(product_id,forecast_target_date) product_id,forecast_id,forecast_target_date,expected_demand
          FROM demand_forecasts WHERE tenant_id=%s
            AND forecast_target_date BETWEEN CURRENT_DATE AND CURRENT_DATE+29
            AND created_at BETWEEN now()-interval '7 days' AND now()
          ORDER BY product_id,forecast_target_date,created_at DESC,forecast_id DESC
        ), forecast AS (
          SELECT product_id,SUM(expected_demand) AS units,array_agg(forecast_id) AS ids
          FROM daily GROUP BY product_id HAVING count(*)=30
        ), stock AS (
          SELECT product_id,SUM(stock_quantity) AS units,array_agg(inventory_id) AS ids
          FROM inventory WHERE tenant_id=%s AND updated_at BETWEEN now()-interval '30 days' AND now()
          GROUP BY product_id
        ) SELECT p.product_id,p.product_name,f.units,s.units,f.ids,s.ids
          FROM products p JOIN forecast f ON f.product_id=p.product_id JOIN stock s ON s.product_id=p.product_id
          WHERE p.tenant_id=%s AND p.deleted_at IS NULL AND s.units>0 AND f.units<s.units*.8
          ORDER BY (s.units-f.units) DESC,p.product_id;""",(tenant_id,tenant_id,tenant_id))
        rows=c.fetchall()
    result=[]
    for pid,name,demand,stock,fids,iids in rows[:max_insights]:
        label=(name.get('en') or name.get('ar') or str(pid)) if isinstance(name,dict) else str(name)
        result.append(Insight(
          message=f"Recorded stock for {label} is {float(stock):g} units; a complete next-30-day forecast totals {float(demand):g}. Review future order quantities before reordering. This does not establish that the product should be discontinued.",
          category='assortment',product_id=str(pid),confidence=REDUCE_CANDIDATE_CONFIDENCE,rule_id='review_excess_stock',
          facts={'forecast_kind':'complete_30_target_days','forecast_total':float(demand),'stock_units':float(stock),
                 'forecast_ids':[str(i) for i in fids],'inventory_ids':[str(i) for i in iids]}))
    return result

import assert from 'node:assert/strict';
import { aggregateDashboard, previewDatabase as db, previewContext as context } from '../src/features/dashboard/config/dashboardPreviewData.js';
const run=(data=db,days=7)=>aggregateDashboard(data,context,days);
const baseline=run();
assert.equal(baseline.revenue,2625);assert.equal(baseline.sales,105);assert.equal(baseline.buckets.reduce((s,b)=>s+b.revenue,0),baseline.revenue);
const invoice={...db.invoices[0],invoice_id:'extra',total_amount:900};
for(const patch of [{tenant_id:'other'},{currency:'USD'},{payment_status:'CANCELLED'},{issue_date:'2026-09-15T00:00:00Z'}]) assert.equal(run({...db,invoices:[...db.invoices,{...invoice,...patch}]}).revenue,baseline.revenue);
assert.equal(run({...db,invoices:[]}).growth,null);
assert.equal(run({...db,inventory:[{...db.inventory[0],stock_quantity:10,reorder_level:10}]}).lowStock.length,1);
assert.equal(run({...db,products:[{...db.products[0],deleted_at:'2026-09-01'}]}).totalProducts,0);
assert.equal(run({...db,tenantCompetitors:[{...db.tenantCompetitors[0],is_tracked:false}]}).trackedCompetitors,0);
assert.equal(run({...db,invoiceItems:[...db.invoiceItems,{...db.invoiceItems[0],tenant_id:'other',quantity:999}]}).sales,baseline.sales);
for(const days of [7,30,90]) {const data=run(db,days);assert.equal(data.buckets.reduce((s,b)=>s+b.revenue,0),data.revenue);}
console.log('Dashboard aggregation: period boundaries, totals, tenant/currency/cancellation isolation, zero baseline, stock threshold and snapshot counts passed.');

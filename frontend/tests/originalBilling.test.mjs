import test from 'node:test';
import assert from 'node:assert/strict';
import { mapPlan } from '../src/features/billing/api/billingApi.js';
import { toOriginalPlan, toOriginalSubscription, toOriginalUsage, toOriginalInvoice } from '../src/features/billing/api/originalBillingModel.js';
import { billingApi } from '../src/features/billing/api/customerBillingApi.js';
import httpClient from '../src/shared/lib/httpClient.js';

test('original cards receive exact backend quantities, units and effective prices', () => {
  const plan = toOriginalPlan(mapPlan({ plan_key:'growth',name:{en:'Growth',ar:'النمو'},self_serve:true,tier_level:2,
    monthly_price:99,limits:{tracked_products:425,document_extraction:2048,web_searches:500,rag_assistant:1000000},
    entitlements:['market_intelligence'],feature_catalog:{document_extraction:{name:'Documents',unit:'KB'}},
    prices:[{period_code:'three-months',amount:267.30,currency:'USD',interval_months:3,discount_percent:10,purchasable:true}] }));
  assert.equal(plan.features.tracked_products.limitValue,425);
  assert.equal(plan.features.document_extraction.unit,'KB');
  assert.equal(plan.features.document_extraction.limitValue,2048);
  assert.equal(plan.features.market_intelligence.type,'boolean');
  assert.equal(plan.features.web_searches,undefined);
  assert.equal(plan.features.rag_assistant,undefined);
  assert.equal(plan.pricingOptions[0].totalPrice,267.30);
});

test('a local free trial is distinct from an existing Stripe trial subscription', () => {
  const local=toOriginalSubscription({assigned:true,planId:'starter',status:'trial',billingStatus:'trialing',hasSubscription:false});
  assert.equal(local.hasStripeSubscription,false);
  const stripe=toOriginalSubscription({...local,billingStatus:'trialing',hasSubscription:true});
  assert.equal(stripe.hasStripeSubscription,true);
  assert.equal(stripe.status,'trialing');
});

test('original usage never changes backend quantities or interprets missing values as unlimited', () => {
  const value=toOriginalUsage({planId:'custom',features:[{feature_code:'document_extraction',unit:'MB',limit:2048,current_usage:19}],entitlements:['market_intelligence']});
  assert.equal(value.limits.document_extraction,2048);
  assert.equal(value.features.document_extraction.unit,'MB');
  assert.equal(value.limits.document_storage_mb,undefined);
  assert.equal(value.features.market_intelligence.type,'boolean');
});

test('original invoice rows preserve amounts, failed states and historical documents', () => {
  const invoice=toOriginalInvoice({invoice_id:'in_test',amount:53.25,currency:'USD',status:'failed',created_at:'2026-10-25',invoice_pdf_url:'https://pay.stripe.com/invoice.pdf'});
  assert.equal(invoice.amount,53.25);assert.equal(invoice.paymentStatus,'failed');assert.equal(invoice.pdfUrl,'https://pay.stripe.com/invoice.pdf');
});

test('original promotion control sends its selected billing term and never submits a client price', async () => {
  const adapter=httpClient.defaults.adapter;const calls=[];
  httpClient.defaults.adapter=async(config)=>{calls.push(config);return {data:{valid:true},status:200,statusText:'OK',headers:{},config};};
  try {
    await billingApi.validateCoupon({code:'SYNTHETIC',planId:'growth',billingPeriod:'six-months',amount:1});
    assert.deepEqual(JSON.parse(calls[0].data),{code:'SYNTHETIC',plan_key:'growth',period_code:'six-months'});
    await billingApi.previewChange({planId:'enterprise',billingPeriod:'monthly'});
    assert.equal(calls[1].url,'/billing/change-plan/preview');
  } finally {httpClient.defaults.adapter=adapter;}
});

test('a rejected promotion response cannot appear as successfully applied', async () => {
  const adapter=httpClient.defaults.adapter;
  httpClient.defaults.adapter=async(config)=>({data:{valid:false,reason:'not_eligible'},status:200,statusText:'OK',headers:{},config});
  try {
    await assert.rejects(billingApi.validateCoupon({code:'SYNTHETIC',planId:'growth',billingPeriod:'monthly'}), {code:'not_eligible'});
  } finally {httpClient.defaults.adapter=adapter;}
});

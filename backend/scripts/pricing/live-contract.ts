import 'dotenv/config';
import assert from 'node:assert/strict';
import {requestPricingRecommendation} from '../../src/modules/pricing/client/pricing.client.js';

if(process.env.PRICING_LIVE_AI!=='1')throw new Error('Set PRICING_LIVE_AI=1 to run two synthetic requests against the configured analytics Space. No database writes.');
const now=new Date().toISOString();
const product={product_name:'Synthetic contract fixture',current_price:10,currency:'JOD',cost_price:6};
const success=await requestPricingRecommendation({product,competitorPrices:[
  {competitor_name:'Synthetic local market',price:8,currency:'JOD',observed_at:now},
  {competitor_name:'Synthetic foreign reference',price:10,currency:'USD',observed_at:now}
],exchangeRates:[{from_currency:'USD',to_currency:'JOD',rate:0.71,as_of:now,source:'synthetic-fixture'}]});
assert.equal(success.result.status,'OK');
if(success.result.status==='OK'){
  assert.equal(success.result.matched_competitor_count,1);
  assert.equal(success.result.suggested_price,8.5);
}
const unknown=await requestPricingRecommendation({product,competitorPrices:[],exchangeRates:null});
assert.equal(unknown.result.status,'UNKNOWN');
console.log('PASS configured Gradio contract: local sample count, 15% movement guardrail, foreign reference exclusion, and UNKNOWN. No KEEL database writes.');

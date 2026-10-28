import test from 'node:test';
import assert from 'node:assert/strict';
import {policyForLegacy,policyFromLegacy,quoteForLegacy,subscriptionForLegacy} from '../src/features/platform/billingLegacyContracts.js';
import {createPlatformBillingCatalogApi} from '../src/features/platform/platformBillingCatalogApi.js';
const policy={currency:'USD',targetGrossMargin:'0.25',fixedPlatformFee:'0',monthlyInfrastructureCost:'0',activePayingTenants:'',roundingIncrement:'0.01',enforceVendorCostRatioFloor:false,approvalEvidence:'SYNTHETIC fixture'};
test('unconfigured policy never fabricates a commercial margin, cost or fee',()=>{
 const p=policyForLegacy();assert.equal(p.currency,'USD');for(const k of ['targetGrossMargin','fixedPlatformFee','monthlyInfrastructureCost','roundingIncrement'])assert.equal(p[k],undefined);
});
test('original policy form creates an explicit USD revision contract',()=>{
 assert.deepEqual(policyFromLegacy(policy),{target_gross_margin:'0.25',enforce_vendor_cost_ratio_floor:false,max_vendor_cost_revenue_ratio:null,fixed_platform_fee_usd:'0',upward_rounding_increment_usd:'0.01',monthly_shared_infrastructure_cost_usd:'0',active_paying_tenant_count:null,approval_evidence:'SYNTHETIC fixture'});
});
for(const [name,changes] of Object.entries({currency:{currency:'JOD'},missingMargin:{targetGrossMargin:''},marginOne:{targetGrossMargin:1},negativeFee:{fixedPlatformFee:-1},nanFee:{fixedPlatformFee:'NaN'},missingEvidence:{approvalEvidence:''},fractionalCount:{activePayingTenants:'1.5'},sharedWithoutCount:{monthlyInfrastructureCost:'1'}}))test('invalid policy rejected: '+name,()=>assert.throws(()=>policyFromLegacy({...policy,...changes})));
test('quote adapter uses frozen server evidence and preserves review state',()=>{
 const q=quoteForLegacy({quote_id:'q',tenant_id:'t',state:'submitted',revision_number:2,configuration:{enabledFeatures:['competitor_management'],refreshFrequency:'weekly'},feature_quantities:{tracked_competitors:3},commercial_terms:{monthlyPriceUsd:'15.00'},pricing_snapshot:{calculationHash:'hash',calculation:{recommendedPrice:'15.00',minimumSafePrice:'14.00',estimatedTotalCost:'10.00'}}});
 assert.equal(q.status,'submitted');assert.equal(q.finalPrice,undefined);assert.equal(q.recommendedPrice,'15.00');assert.equal(q.pricingAvailable,true);assert.equal(q.quoteFeatures[1].configuration.monitoringFrequencyMinutes,10080);assert.equal(q.quoteFeatures[0].limitValue,3);
});
test('subscription display preserves trial and dates rather than inventing a new period',()=>{
 const s=subscriptionForLegacy({subscription_id:'s',tenant_id:'t',business_name:'Synthetic',plan_key:'growth',status:'trialing',trial_end:'2026-11-01',current_period_end:'2026-11-01',scheduled_plan_key:'starter',cancel_at_period_end:false},[{id:'growth',name:'Growth'},{id:'starter',name:'Starter'}]);
 assert.equal(s.status,'trialing');assert.equal(s.plan.name,'Growth');assert.equal(s.tenant.businessName,'Synthetic');assert.equal(s.currentPeriodEnd,'2026-11-01');assert.equal(s.scheduledPlan.name,'Starter');assert.equal(s.scheduledEffectiveAt,undefined);
});
test('original save creates a draft only, activation is a distinct explicit operation',async()=>{
 const calls=[];const api=createPlatformBillingCatalogApi({billing:{createPolicy:async b=>{calls.push(['draft',b]);return {status:'draft'};},activatePolicy:async(id,b)=>calls.push(['activate',id,b])}});
 assert.equal((await api.updateCustomPlanPricingPolicy(policy)).status,'draft');assert.equal(calls.length,1);await api.activateCustomPlanPricingPolicy('p','SYNTHETIC approval');assert.equal(calls[1][2].approval_evidence,'SYNTHETIC approval');
});
test('unavailable calculation rejects, and no synthetic pricing success can be shown',async()=>{
 const api=createPlatformBillingCatalogApi({billing:{calculateQuote:async()=>({pricingAvailable:false,reasons:['active_pricing_policy_missing']})}});await assert.rejects(api.calculateCustomPlanQuote('q'),/active_pricing_policy_missing/);
});
test('quote creation retries retain creation and submission identity',async()=>{
 const calls=[];const api=createPlatformBillingCatalogApi({billing:{createQuote:async b=>{calls.push(b.idempotency_key);return{quote_id:'q'};},submitQuote:async(id,b)=>calls.push(b.idempotency_key)}});
 const p={tenantId:'t',idempotencyKey:'same-intent',features:[{featureId:'team_seats',limitValue:3}]};await api.createCustomPlanQuote(p);await api.createCustomPlanQuote(p);assert.deepEqual(calls,['same-intent','same-intent:submit','same-intent','same-intent:submit']);
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { newPolicy, policyPayload, analysisPayload, ASSUMPTION_FIELDS, INTERNAL_PLANS, INTERNAL_SCENARIOS } from '../src/features/platform/pricingStudio.js';
import { createPlatformBillingApi } from '../src/features/platform/platformBillingApi.js';

test('new policy leaves economic assumptions explicitly unconfigured',()=>{
 const form=newPolicy(); for(const key of ASSUMPTION_FIELDS) assert.equal(form[key],'');
 assert.deepEqual(form.feature_treatments,{});assert.equal(form.reason,'');
 for(const plan of INTERNAL_PLANS)for(const s of INTERNAL_SCENARIOS){assert.equal(form.internal_costs_by_plan[plan][s].monthly_jod,'');assert.equal(form.internal_costs_by_plan[plan][s].status,'provisional');}
 const legacy=newPolicy({assumptions:{infrastructure_jod:'4',support_jod:'3',operations_jod:'2'}});
 assert.deepEqual(legacy.internal_costs_by_plan,form.internal_costs_by_plan);
 assert.throws(()=>policyPayload(form),/not configured/);
});
test('policy transport preserves exact decimal strings and appends an evidence-bearing version',()=>{
 const form={...newPolicy(),annual_allowance_cycles:'12',max_rate_age_days:'90',usd_to_jod:'0.709000000001',reason:'Synthetic evidence'};
 for(const plan of INTERNAL_PLANS)for(const s of INTERNAL_SCENARIOS)form.internal_costs_by_plan[plan][s].monthly_jod='0.000001';
 form.internal_costs_by_plan.growth.stress={monthly_jod:'12.345678',status:'approved',evidence_ref:'Synthetic invoice',measured_from:'2026-10-01',measured_to:'2026-10-31',note:'Test only'};
 const body=policyPayload(form);assert.equal(body.assumptions.usd_to_jod,'0.709000000001');
 assert.equal(body.assumptions.assumptions_schema_version,2);assert.equal(body.assumptions.infrastructure_jod,undefined);
 assert.deepEqual(body.assumptions.internal_costs_by_plan.growth.stress,form.internal_costs_by_plan.growth.stress);
 assert.deepEqual(newPolicy({assumptions:body.assumptions}).internal_costs_by_plan.growth.stress,form.internal_costs_by_plan.growth.stress);
 assert.equal(body.assumptions.annual_allowance_cycles,12);assert.equal(body.assumptions.cost_binding_policy_id,null);
});
test('simulation sends configuration, never a price or cost estimate; existing plan analysis omits simulation',()=>{
 assert.deepEqual(analysisPayload('starter','analyze',{},[],null,''),{plan_key:'starter'});
 assert.deepEqual(analysisPayload('growth','simulate',{ai_credits:'999',tracked_competitors:''},['rag_assistant'],'daily','policy'),{
  plan_key:'growth',policy_id:'policy',simulation:{limits:{ai_credits:999,tracked_competitors:null},entitlements:['rag_assistant'],refresh_frequency:'daily'}});
});
test('studio API uses the owner billing boundary and no plan-price update',async()=>{
 const calls=[];const client={get:async path=>{calls.push(['GET',path]);return{data:{}};},post:async(path,body)=>{calls.push(['POST',path,body]);return{data:{}};}};
 const api=createPlatformBillingApi(client);await api.pricingStudio();await api.analyzePlan({plan_key:'starter'});await api.createAnalysisPolicy({reason:'Synthetic'});await api.analysisHistory();
 assert.deepEqual(calls.map(c=>c.slice(0,2)),[['GET','/platform/billing/pricing-studio'],['POST','/platform/billing/pricing-studio/analyze'],['POST','/platform/billing/pricing-studio/policies'],['GET','/platform/billing/pricing-studio/history']]);
});
test('Pricing Studio translations cover both languages including every policy field and review warning',()=>{
 const en=JSON.parse(readFileSync('src/assets/locales/en.json','utf8')).billing.pricingStudio;
 const ar=JSON.parse(readFileSync('src/assets/locales/ar.json','utf8')).billing.pricingStudio;
 const keys=o=>Object.entries(o).flatMap(([k,v])=>typeof v==='object'?keys(v).map(x=>k+'.'+x):[k]).sort();
 assert.deepEqual(keys(en),keys(ar));for(const k of ASSUMPTION_FIELDS){assert.ok(en.fields[k]);assert.ok(ar.fields[k]);}
 for(const locale of [en,ar]){assert.ok(locale.statuses.PROVISIONAL);assert.ok(locale.warnings.TIER_INTERNAL_ASSUMPTIONS_MISSING);for(const plan of INTERNAL_PLANS)assert.ok(locale.tierInternal.plans[plan]);}
});

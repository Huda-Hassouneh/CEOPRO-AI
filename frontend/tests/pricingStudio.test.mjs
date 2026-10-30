import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { newPolicy, policyPayload, analysisPayload, ASSUMPTION_FIELDS } from '../src/features/platform/pricingStudio.js';
import { createPlatformBillingApi } from '../src/features/platform/platformBillingApi.js';

test('new policy leaves economic assumptions explicitly unconfigured',()=>{
 const form=newPolicy(); for(const key of ASSUMPTION_FIELDS) assert.equal(form[key],'');
 assert.deepEqual(form.feature_treatments,{});assert.equal(form.reason,'');
});
test('policy transport preserves exact decimal strings and appends an evidence-bearing version',()=>{
 const form={...newPolicy(),annual_allowance_cycles:'12',max_rate_age_days:'90',usd_to_jod:'0.709000000001',infrastructure_jod:'0.000001',reason:'Synthetic evidence'};
 const body=policyPayload(form);assert.equal(body.assumptions.usd_to_jod,'0.709000000001');assert.equal(body.assumptions.infrastructure_jod,'0.000001');
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
});

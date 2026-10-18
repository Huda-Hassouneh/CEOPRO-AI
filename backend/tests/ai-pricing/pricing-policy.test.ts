import test from 'node:test';
import assert from 'node:assert/strict';
import {comparablePrices,enforcePriceGuardrails,freshDate,localMarketTarget,summarizeMarket,validProduct} from '../../src/modules/pricing/service/pricing.policy.js';
import type {MarketPricePoint,PricingProductContext,PricingRate} from '../../src/modules/pricing/types/pricing.types.js';
const product:PricingProductContext={productId:'test',productName:'Rice',currentPrice:10,costPrice:null,currency:'JOD',version:1};
const now=new Date('2026-10-15T12:00:00Z');
const point=(patch:Partial<MarketPricePoint>={}):MarketPricePoint=>({competitorId:'a',competitorPriceId:'1',mappingId:'m',competitorName:'Market',price:8,currency:'JOD',observedAt:new Date(now.getTime()-60000),...patch});
test('only one latest positive, timely observation per competitor; no older fallback behind an invalid latest',()=>{
 const points=[point({competitorPriceId:'old',price:1,observedAt:new Date(now.getTime()-120000)}),point(),point({competitorId:'b',price:0}),point({competitorId:'c',price:-1}),point({competitorId:'d',observedAt:new Date(now.getTime()+1)}),point({competitorId:'e',observedAt:new Date('2026-09-01')})];
 const sources=comparablePrices(points,[],'JOD',now);assert.equal(sources.length,1);assert.equal(sources[0].original_price,8);
 assert.equal(comparablePrices([point({price:0}),point({observedAt:new Date(now.getTime()-120000)})],[],'JOD',now).length,0);
});
test('FX requires the correct direction, positive fresh rate and known source; originals remain intact',()=>{
 const rates:PricingRate[]=[{fromCurrency:'USD',toCurrency:'JOD',rate:0.71,asOf:now,source:'fixture-bank'}];
 const p=point({currency:'USD',price:10});const [source]=comparablePrices([p],rates,'JOD',now);
 assert.equal(source.converted_price,7.1);assert.equal(source.original_price,10);assert.equal(source.original_currency,'USD');assert.equal(source.conversion?.source,'fixture-bank');
 for(const patch of [{rate:0},{rate:-1},{rate:NaN},{source:''},{source:'unspecified'},{asOf:new Date('2026-01-01')},{asOf:new Date(now.getTime()+1000)},{fromCurrency:'JOD',toCurrency:'USD'}])assert.equal(comparablePrices([p],[{...rates[0],...patch}],'JOD',now).length,0);
 assert.equal(comparablePrices([p],[],'JOD',now).length,0);
});
test('market mean and median use exactly the supplied positive comparison sample',()=>{
 assert.deepEqual(summarizeMarket([1,2,10,11]),{min:1,max:11,average:6,median:6,count:4});
 assert.equal(summarizeMarket([0,-1,NaN]).average,null);
 assert.equal(summarizeMarket([0.1,0.2]).average,0.15);
});
test('5% boundaries are inclusive holds, with raise/lower targets outside the band',()=>{
 for(const current of [9.5,10,10.5])assert.equal(localMarketTarget(current,10),current);
 for(const current of [9.499,10.501])assert.equal(localMarketTarget(current,10),10);
});
test('15% movement limit and cost floor are independent; floor overrides the cap explicitly',()=>{
 assert.equal(enforcePriceGuardrails(product,1).suggestedPrice,8.5);
 assert.equal(enforcePriceGuardrails(product,100).suggestedPrice,11.5);
 assert.equal(enforcePriceGuardrails(product,10).action,'hold');
 const result=enforcePriceGuardrails({...product,costPrice:12},8);
 assert.equal(result.suggestedPrice,13.2);assert.equal(result.floor,13.2);assert.equal(result.action,'raise');
 assert.equal(result.movementCapOverridden,true);assert.equal(result.marginClamped,true);
 assert.equal(enforcePriceGuardrails(product,10).marginClamped,null);
 assert.equal(enforcePriceGuardrails({...product,costPrice:0},10).floor,0);
});
test('currency rounding respects JOD fils, zero-decimal currencies and strict movement bounds',()=>{
 assert.equal(enforcePriceGuardrails({...product,currentPrice:1.001,costPrice:1.002},1).floor,1.103);
 assert.equal(enforcePriceGuardrails({...product,currentPrice:100,currency:'JPY'},1000).suggestedPrice,115);
 const result=enforcePriceGuardrails({...product,currentPrice:1.01,currency:'USD'},100);
 assert.equal(result.suggestedPrice,1.16);assert.ok(result.suggestedPrice<=1.01*1.15);
 assert.throws(()=>enforcePriceGuardrails(product,0));
});
test('invalid catalog prices/costs and future/stale timestamps fail closed',()=>{
 assert.equal(validProduct(product),true);
 for(const patch of [{currentPrice:0},{currentPrice:-1},{costPrice:-1},{currency:'jod'},{currentPrice:Infinity}])assert.equal(validProduct({...product,...patch}),false);
 assert.equal(freshDate(new Date('invalid'),now,30),false);
});

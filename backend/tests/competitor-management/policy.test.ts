import assert from 'node:assert/strict';
import { test } from 'node:test';
import { websiteIdentity,competitorCreateSchema,competitorUpdateSchema } from '../../src/modules/competitors/types/competitors.validation.js';
import { monitoringMinutes,priceComparison,priceActivity } from '../../src/modules/competitors/service/competitors.policy.js';
const now=new Date('2026-10-13T10:00:00Z');
const row=(id:string,currency='JOD',price=5,date='2026-10-12T10:00:00Z')=>({competitor_price_id:id,currency,scraped_price:price,observed_at:new Date(date),source_status:'ALLOWED',is_available:true,is_exact_data:true});
test('website identities normalize host and trailing slash but preserve distinct marketplace stores',()=>{
 assert.equal(websiteIdentity('https://www.EXAMPLE.com/store/'),'example.com/store');
 assert.equal(websiteIdentity('http://example.com/store?utm_source=x'),'example.com/store');
 assert.notEqual(websiteIdentity('https://example.com/store/a'),websiteIdentity('https://example.com/store/b'));
 for(const website of ['javascript:alert(1)','https://user:password@example.com','http://localhost']) assert.equal(competitorCreateSchema.safeParse({name:'Store',website}).success,false);
 assert.equal(competitorCreateSchema.safeParse({name:' ',website:'https://example.com'}).success,false);
 assert.equal(competitorCreateSchema.safeParse({name:'Store',website:'https://example.com',tenantId:'other'}).success,false);
 assert.equal(competitorUpdateSchema.safeParse({alias:null}).success,true);
});
test('comparison uses latest same-currency exact allowed observation and never falls back behind rejection',()=>{
 const prices=[row('usd','USD',100),row('jod','JOD',5,'2026-10-11T10:00:00Z')];
 assert.equal(priceComparison(prices,'JOD',4,true,now,7).priceDifference,1);
 assert.equal(priceComparison(prices,'JOD',4,true,now,7).priceDifferencePercent,25);
 assert.equal(priceComparison(prices,'JOD',0,true,now,7).priceDifferencePercent,null);
 assert.equal(priceComparison(prices,'JOD',4,false,now,7).reason,'MATCH_UNCONFIRMED');
 assert.equal(priceComparison(prices,'EUR',4,true,now,7).reason,'CURRENCY_MISMATCH');
 for(const [change,reason] of [[{source_status:'BLOCKED'},'SOURCE_BLOCKED'],[{is_available:false},'UNAVAILABLE'],[{is_exact_data:false},'ESTIMATED_PRICE'],[{scraped_price:-1},'INVALID_PRICE'],[{observed_at:new Date('2026-10-14')},'INVALID_DATE']] as const) {
  const result=priceComparison([{...row('bad'),...change},row('old','JOD',3,'2026-10-10')],'JOD',4,true,now,7);
  assert.equal(result.competitorPrice,null);assert.equal(result.reason,reason);
 }
 assert.equal(priceComparison([row('old','JOD',3,'2026-09-01')],'JOD',4,true,now,7).reason,'STALE_PRICE');
 assert.equal(priceComparison(prices,'JOD',4,true,now,7,false).reason,'SOURCE_BLOCKED');
});
test('activity separates currencies and excludes invalid adjacent observations and tied timestamps',()=>{
 const result=priceActivity([row('new','JOD',5),row('usd','USD',100),row('old','JOD',4,'2026-10-11'),row('old-usd','USD',90,'2026-10-10')],now,7);
 assert.equal(result.length,2);assert.ok(result.every(r=>r.newPrice-r.previousPrice===1 || r.newPrice-r.previousPrice===10));
 assert.deepEqual(priceActivity([row('a'),row('b','JOD',4)],now,7),[]);
 assert.deepEqual(priceActivity([row('a'),{...row('b','JOD',4,'2026-10-11'),is_available:false}],now,7),[]);
});
test('monitoring uses accepted plan metadata, including custom values, without fabricated legacy defaults',()=>{
 assert.equal(monitoringMinutes({configuration:{monitoringFrequencyMinutes:1440}}),1440);
 assert.equal(monitoringMinutes({configuration:{monitoringFrequencyMinutes:360}}),360);
 assert.equal(monitoringMinutes({configuration:{monitoringFrequencyMinutes:720}}),720);
 for(const value of [null,{}, {configuration:{monitoringFrequencyMinutes:0}},{configuration:{monitoringFrequencyMinutes:'360'}}]) assert.equal(monitoringMinutes(value),null);
});

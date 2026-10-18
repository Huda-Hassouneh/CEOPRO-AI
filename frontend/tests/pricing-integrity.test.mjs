import test from 'node:test';import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pricingRequestRetryable,newPricingRequestId} from '../src/features/market-intelligence/utils/pricingRequest.js';
import {buildPricingRows,pricingErrorMessage} from '../src/features/market-intelligence/utils/marketIntelligencePresentation.js';
const error=(reason,status)=>({response:{status,data:{error:{code:'PRICING_'+reason,details:{reason}}}}});
test('uncertain network/server failures preserve the request identity; definitive failures do not',()=>{
 assert.equal(pricingRequestRetryable({code:'ERR_NETWORK'}),true);
 assert.equal(pricingRequestRetryable(error('REQUEST_PENDING',409)),true);
 assert.equal(pricingRequestRetryable(error('SERVER_ERROR',500)),true);
 for(const reason of ['INVALID_AI_RESULT','SOURCE_CHANGED','REQUEST_FAILED','REQUEST_EXPIRED','REQUEST_CONFLICT'])assert.equal(pricingRequestRetryable(error(reason,reason==='INVALID_AI_RESULT'?502:409)),false);
 assert.equal(pricingRequestRetryable(error('QUOTA_EXHAUSTED',402)),false);
 const a=newPricingRequestId(),b=newPricingRequestId();assert.match(a,/^[0-9a-f-]{36}$/);assert.notEqual(a,b);
});
test('UNKNOWN cannot resurrect incompatible overview statistics; history exposes localised explanations and stale state',()=>{
 const selectedProduct={id:'p',name:'Rice',currency:'JOD'};
 const [row]=buildPricingRows({selectedProduct,overviewRows:[{productId:'p',marketMin:100,marketAverage:150}],
  recommendation:{status:'UNKNOWN',market_min:null,market_avg:null,market_max:null,market_median:null,matched_competitor_count:0,explanation_i18n:{en:'No prices',ar:'لا توجد أسعار'},is_stale:true}});
 assert.equal(row.marketMin,null);assert.equal(row.marketAverage,null);assert.equal(row.action,null);assert.equal(row.suggestedPrice,null);
 assert.equal(row.explanation.ar,'لا توجد أسعار');assert.equal(row.dataStatus,'stale');
});
for(const locale of ['en','ar'])test(`${locale}: pricing-specific errors and all new customer-facing copy are translated`,()=>{
 const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`,import.meta.url)));
 const t=key=>key.split('.').reduce((v,k)=>v?.[k],messages);
 for(const [reason,key] of [['REQUEST_PENDING','pending'],['SOURCE_CHANGED','sourceChanged'],['INVALID_AI_RESULT','invalidResult']])assert.equal(pricingErrorMessage(error(reason,409),t),t('marketMain.pricingFix.errors.'+key));
 const values=messages.marketMain.pricingFix;assert.ok(values.referenceOnly);assert.ok(values.chargePolicy);assert.ok(values.remainingCredits);assert.ok(values.stale);
});

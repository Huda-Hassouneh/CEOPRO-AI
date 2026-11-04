import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { quoteHasVerifiedActivation } from '../src/features/billing/utils/customQuoteState.js';

test('quote acceptance and a redirect do not imply verified paid activation', () => {
  assert.equal(quoteHasVerifiedActivation({state:'accepted',events:[{action:'accepted'}]}),false);
  assert.equal(quoteHasVerifiedActivation({state:'accepted',events:[{action:'checkout_session_completed'}]}),false);
  assert.equal(quoteHasVerifiedActivation({events:[{action:'contract_activated'}]}),true);
});
test('Custom Arabic translations have readable text and matching interpolation keys', () => {
  const en=JSON.parse(readFileSync(new URL('../src/assets/locales/en.json',import.meta.url),'utf8')).billing.customPlan;
  const ar=JSON.parse(readFileSync(new URL('../src/assets/locales/ar.json',import.meta.url),'utf8')).billing.customPlan;
  const visit=(left,right)=>Object.entries(left).forEach(([key,value])=>{
    if(typeof value==='object')return visit(value,right[key]);
    assert.equal(typeof right[key],'string',key);
    assert.ok(!right[key].includes('??'),key);
    assert.deepEqual(right[key].match(/\{\{\w+\}\}/g)||[],value.match(/\{\{\w+\}\}/g)||[],key);
  });visit(en,ar);
});

test('final vendor ratio review has readable English and Arabic explanations', () => {
  for (const locale of ['en', 'ar']) {
    const messages = JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`, import.meta.url), 'utf8'));
    for (const reason of ['VENDOR_COST_RATIO_EXCEEDED', 'VENDOR_COST_RATIO_UNVERIFIABLE']) {
      const explanation = messages.billing.customPlan.reviewReasons[reason];
      assert.ok(explanation.length > 20);
      assert.ok(!explanation.includes(reason));
      if (locale === 'ar') assert.match(explanation, /[\u0600-\u06ff]/);
    }
  }
});

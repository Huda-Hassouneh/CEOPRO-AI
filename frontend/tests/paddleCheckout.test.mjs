import test from 'node:test';
import assert from 'node:assert/strict';
import { paddleCheckoutOptions, openPaddleCheckout } from '../src/features/billing/utils/paddleCheckout.js';
const op='operation', txn='txn_'+'a'.repeat(26);
const details={operation_id:op,provider:'paddle',environment:'test',transaction_id:txn};
test('Paddle handoff accepts only original authenticated transaction, never URL terms',()=>{
  const o=paddleCheckoutOptions(details,op,txn,'ar');
  assert.deepEqual(o,{transactionId:txn,settings:{displayMode:'overlay',allowLogout:false,allowedPaymentMethods:['card'],locale:'ar'}});
  for(const patch of [{operation_id:'other'},{provider:'stripe'},{environment:'live'},{transaction_id:'txn_'+'b'.repeat(26)}])
    assert.throws(()=>paddleCheckoutOptions({...details,...patch},op,txn));
  assert.throws(()=>paddleCheckoutOptions(details,op,'txn_malformed'));
  assert.equal('items' in o,false);assert.equal('customer' in o,false);
});
test('disabled and LIVE credentials cannot load SDK or dispatch Checkout',async()=>{
  await assert.rejects(openPaddleCheckout(details,op,txn,'en',{}));
  await assert.rejects(openPaddleCheckout(details,op,txn,'en',{VITE_RECURRING_JOURNEY_ENABLED:'true',VITE_PADDLE_CHECKOUT_ENABLED:'true',VITE_PADDLE_CLIENT_TOKEN:'live_synthetic'}));
});

test('switching identity while SDK loads prevents old operation Checkout from opening',async()=>{
  const previousWindow=globalThis.window,previousDocument=globalThis.document;
  let script,opens=0;
  globalThis.window={location:{origin:'https://merchant.example.test'},Paddle:{Environment:{set(){assert.fail('aborted identity cannot initialize');}},Checkout:{open(){opens++;}}}};
  globalThis.document={createElement(){script={};return script;},head:{append(){}}};
  try{
    const controller=new AbortController();
    const result=openPaddleCheckout(details,op,txn,'en',{VITE_RECURRING_JOURNEY_ENABLED:'true',VITE_PADDLE_CHECKOUT_ENABLED:'true',VITE_PADDLE_CLIENT_TOKEN:'test_synthetic',VITE_PADDLE_CHECKOUT_ORIGIN:'https://merchant.example.test'},controller.signal);
    controller.abort();script.onload();
    await assert.rejects(result,/canceled/);assert.equal(opens,0);
  }finally{globalThis.window=previousWindow;globalThis.document=previousDocument;}
});

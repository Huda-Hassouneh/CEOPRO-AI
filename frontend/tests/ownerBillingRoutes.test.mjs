import test from 'node:test';
import assert from 'node:assert/strict';
import { ownerBillingDestination } from '../src/features/platform/ownerBillingRoutes.js';

test('historical owner billing link preserves pricing and quote review context', () => {
  const search='?python=1&tab=quotes&quote=synthetic-quote';
  assert.deepEqual(ownerBillingDestination({search,hash:'#evidence'}),{
    pathname:'/admin/billing',search,hash:'#evidence',
  });
});
test('owner billing redirect always targets the original internal owner shell', () => {
  assert.deepEqual(ownerBillingDestination({pathname:'https://untrusted.example'}),{
    pathname:'/admin/billing',search:'',hash:'',
  });
});

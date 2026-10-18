import {test,expect} from '@playwright/test';
const base=process.env.COMPETITOR_API_URL;
const token=process.env.COMPETITOR_TEST_TOKEN;
const id=process.env.COMPETITOR_TEST_COMPETITOR_ID;
test.describe('Competitor Management: opt-in deployed API checks',()=>{
 test.skip(!base || !token || !id,'Configure a prepared tenant, token and existing competitor fixture for live checks.');
 const headers={Authorization:`Bearer ${token}`};
 test('list preserves its array contract and returns capacity metadata',async({request})=>{
  const response=await request.get(`${base}/competitors`,{headers});expect(response.status()).toBe(200);
  const body=await response.json();expect(Array.isArray(body.data)).toBe(true);expect(body.meta.capacity).toHaveProperty('currentUsage');
 });
 test('profile uses product currency and explains unavailable comparisons',async({request})=>{
  const response=await request.get(`${base}/competitors/${id}`,{headers});expect(response.status()).toBe(200);
  const body=await response.json();expect(body.data.id).toBe(id);
  for(const row of body.data.mappedProducts){expect(typeof row.currency).toBe('string');if(row.reason)expect(row.competitorPrice).toBeNull();}
 });
 test('malformed competitor ID is rejected',async({request})=>{
  const response=await request.get(`${base}/competitors/not-a-uuid`,{headers});expect(response.status()).toBe(400);
 });
 test('strict create validation rejects an injected tenant',async({request})=>{
  const response=await request.post(`${base}/competitors`,{headers,data:{name:'Validation fixture',website:'https://example.invalid',tenant_id:'injected'}});expect(response.status()).toBe(400);
 });
});

// Collection needs an agreed deployed trigger and authorized worker fixtures.
test('live AI discovery and approved collection',async()=>{
 test.skip(true,'Discovery trigger and worker fixtures remain an integration dependency; no collection request is made.');
});

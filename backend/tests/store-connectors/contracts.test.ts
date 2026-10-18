import test from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import {storeUrl,connectSchema,productsSchema,ordersSchema} from '../../src/modules/dataconnection/store/contracts.js';
import {sealCredentials,openCredentials} from '../../src/modules/dataconnection/store/vault.js';
test('store input rejects private/non-HTTPS endpoints, credentials in URLs and scope injection',()=>{
 for(const value of ['http://shop.example','https://127.0.0.1','https://localhost','https://user:secret@shop.example','https://shop.example?key=value','https://shop.example/%2e%2e','https://shop.example:8443'])assert.throws(()=>storeUrl(value),/INVALID_STORE_URL/);
 const input={url:'https://shop.example',consumerKey:'ck_'+'a'.repeat(40),consumerSecret:'cs_'+'b'.repeat(40),consent:true};
 assert.equal(connectSchema.safeParse(input).success,true);assert.equal(connectSchema.safeParse({...input,tenantId:'forged'}).success,false);assert.equal(connectSchema.safeParse({...input,consent:false}).success,false);
 assert.equal(productsSchema.safeParse({contractVersion:2,items:[],hasMore:true}).success,true);assert.equal(ordersSchema.safeParse({items:[{externalId:'1',lines:[{quantity:-1}]}],hasMore:false}).success,false);
});
test('credential encryption authenticates source scope, detects tampering and uses a new nonce on every write',()=>{
 process.env.STORE_CONNECTOR_ENCRYPTION_KEY=randomBytes(32).toString('hex');
 const value={key:'read-key',secret:'private-secret'},a=sealCredentials(value,'tenant-a','source-a'),b=sealCredentials(value,'tenant-a','source-a');
 assert.notEqual(a,b);assert.deepEqual(openCredentials(a,'tenant-a','source-a'),value);assert.ok(!a.includes(value.secret));
 assert.throws(()=>openCredentials(a,'tenant-b','source-a'));assert.throws(()=>openCredentials(a,'tenant-a','source-b'));
 const parts=a.split('.');parts[2]='0'.repeat(32);assert.throws(()=>openCredentials(parts.join('.'),'tenant-a','source-a'));
});

test('v2 accounting validates payment evidence and exact totals at the Node boundary',async()=>{
 const {validateStoreOrder}=await import('../../src/modules/dataconnection/store/invoices.repo.js');
 const invoice={currency:'JOD',issuedAt:'2026-10-10T10:00:00Z',paidAt:null,paymentStatus:'UNPAID',subtotal:'0',tax:'0',total:'0',merchandise:'0',shipping:'0',fees:'0',discount:'0',originalTotal:'0',refundedTotal:'0',items:[]};
 const value={externalId:'1',modifiedAt:'2026-10-10T10:00:00Z',status:'completed',invoice,lines:[]};
 const parsed=ordersSchema.parse({contractVersion:2,items:[value],hasMore:false});validateStoreOrder(parsed.items[0]);
 assert.equal(ordersSchema.safeParse({items:[],hasMore:false}).success,false,'Old adapter payload must fail closed');
 assert.throws(()=>validateStoreOrder({...parsed.items[0],invoice:{...invoice,paymentStatus:'PAID'}}),/TOTAL_MISMATCH/);
 assert.throws(()=>validateStoreOrder({...parsed.items[0],invoice:{...invoice,total:'1'}}),/TOTAL_MISMATCH/);
});

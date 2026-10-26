import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';import {readFileSync} from 'node:fs';import httpClient from '../src/shared/lib/httpClient.js';import {ingestionApi} from '../src/features/data-ingestion/api/ingestionApi.js';
const read=p=>readFileSync(new URL('../src/'+p,import.meta.url),'utf8');
test('original product form keeps bilingual fields, GTIN/SKU and Python version binding',()=>{const form=read('features/products/components/OriginalCatalogProductForm.jsx'),page=read('features/products/pages/ProductFormPage.jsx');assert.match(form,/\['en', 'ar'\]/);assert.match(form,/catalog.fields.sku/);assert.match(form,/validGtin/);assert.match(page,/expected_version:input.expectedVersion/);assert.match(page,/initial_stock_quantity/);});
test('manual upload retries are tenant/file bound and retain request key until success',()=>{const api=read('features/data-ingestion/api/ingestionApi.js');assert.match(api,/keel.upload.\$\{tenant\}/);assert.match(api,/SHA-256/);assert.match(api,/Idempotency-Key/);assert.match(api,/pendingUploadKeys/);});
test('original structured review preserves explicit confirmation and separate supported upload paths',()=>{const review=read('features/data-ingestion/components/StructuredImportReview.jsx'),panel=read('features/data-ingestion/components/StructuredBusinessImport.jsx'),page=read('features/data-connections/pages/ConnectDataPage.jsx');assert.match(review,/reviewChanges/);assert.match(review,/confirmImport/);assert.match(panel,/review.reviewHash/);assert.match(page,/StructuredBusinessImport/);assert.match(page,/ingestionApi.prepareFiles/);});
test('structured API adapter transmits real Python preview/review/confirm contracts',async t=>{const calls=[];const server=http.createServer((req,res)=>{let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{calls.push({url:req.url,method:req.method,body,key:req.headers['idempotency-key']});res.setHeader('Content-Type','application/json');res.end(JSON.stringify({draftId:'fixture-draft',reviewHash:'a'.repeat(64),canonical_write_performed:req.url.endsWith('/confirm')}));});});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const prior=httpClient.defaults.baseURL;httpClient.defaults.baseURL=`http://127.0.0.1:${server.address().port}`;t.after(()=>{httpClient.defaults.baseURL=prior;server.close();});const file=new File(['sku,stock_quantity\nFIXTURE,0'],'fixture.csv',{type:'text/csv'});await ingestionApi.previewBusinessImport(file,'inventory');await ingestionApi.reviewBusinessImport('inventory','fixture-draft',{});const result=await ingestionApi.confirmBusinessImport('inventory','fixture-draft',{},'a'.repeat(64));assert.equal(result.canonical_write_performed,true);assert.match(calls[0].url,/structured-imports\/preview\?kind=inventory/);assert.ok(calls[0].key);assert.equal(calls[1].method,'POST');assert.deepEqual(JSON.parse(calls[2].body),{choices:{},reviewHash:'a'.repeat(64)});});


test('original catalog components use Python versioned contracts without replacing main product pages',()=>{
 const routes=readFileSync(new URL('../src/app/router/index.jsx',import.meta.url),'utf8');assert.match(routes,/path:'\/catalog'/);assert.match(routes,/<ProductsListPage/);assert.match(routes,/<ProductHubPage/);
 const catalog=readFileSync(new URL('../src/features/products/pages/CatalogPage.jsx',import.meta.url),'utf8');assert.match(catalog,/<CatalogTable/);assert.match(catalog,/<GtinImport/);assert.match(catalog,/OriginalCatalogProductForm/);
 const api=readFileSync(new URL('../src/features/products/api/catalogApi.js',import.meta.url),'utf8');assert.match(api,/expected_version:input.expectedVersion/);assert.match(api,/gtin-import\/apply/);assert.doesNotMatch(api,/mock|nodejs/i);
});

test('MPI history reads persisted evidence and all subject caches include tenant identity',()=>{
 const panel=readFileSync(new URL('../src/features/market-intelligence/components/MarketPerceptionPanel.jsx',import.meta.url),'utf8');
 for(const key of ['mpi-products','mpi-competitors','mpi-summary','mpi-history'])assert.ok(panel.includes("['"+key+"',tenant"));
 const api=readFileSync(new URL('../src/features/market-intelligence/api/mpiApi.js',import.meta.url),'utf8');assert.match(api,/get\('\/mpi\/history'/);
});


test('original GTIN upload sends a multipart file instead of the shared JSON default',async t=>{
 const {productsApi}=await import('../src/features/products/api/catalogApi.js');let captured;
 const server=http.createServer((req,res)=>{let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{captured={type:req.headers['content-type'],body};res.setHeader('Content-Type','application/json');res.end('{"rows":[]}');});});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const previous=httpClient.defaults.baseURL;httpClient.defaults.baseURL=`http://127.0.0.1:${server.address().port}`;t.after(()=>{httpClient.defaults.baseURL=previous;server.close();});
 await productsApi.previewGtins(new File(['sku,gtin\nFIXTURE,3017620422003'],'fixture.csv',{type:'text/csv'}));assert.match(captured.type,/multipart\/form-data; boundary=/);assert.match(captured.body,/name="file"; filename="fixture.csv"/);assert.match(captured.body,/FIXTURE,3017620422003/);
});


test('source catalog actions use explicit preview/hash confirmation and retain canonical links',()=>{
 const api=read('features/data-connections/api/dataConnectionsApi.js'),panel=read('features/data-connections/components/ProviderRecordsPanel.jsx');
 assert.match(api,/catalog-preview/);assert.match(api,/catalog-post/);assert.match(panel,/preview_hash:catalogPlan.preview_hash/);assert.match(panel,/catalogPlan.eligible/);assert.match(panel,/canonical_product_id/);assert.match(panel,/<Modal/);
 for(const locale of ['en','ar']){const bundle=JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`,import.meta.url),'utf8'));assert.ok(bundle.connectData.providerRecords.catalogCreate);assert.ok(bundle.connectData.providerRecords.catalogFindings.identity_conflict);}
});

test('pricing requests preserve one retry identity until a successful acknowledgement',()=>{
 const api=read('features/pricing/api/pricingApi.js');assert.match(api,/keel.pricing.\$\{tenant\}.\$\{productId\}/);assert.match(api,/Idempotency-Key/);assert.match(api,/pendingRequests.delete/);assert.match(api,/sessionStorage\?\.removeItem/);
});

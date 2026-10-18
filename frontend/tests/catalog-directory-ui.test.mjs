import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'vite';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { MemoryRouter } from 'react-router-dom';

// Render the actual shared/table components: no production preview or API changes.
test('catalog and competitor tables retain identity, permissions and localized empty states', async () => {
  const vite = await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'});
  try {
    const {CatalogTable} = await vite.ssrLoadModule('/src/features/products/components/CatalogTable.jsx');
    const {CompetitorTable} = await vite.ssrLoadModule('/src/features/market-intelligence/components/CompetitorTable.jsx');
    const {default:RecordSummary} = await vite.ssrLoadModule('/src/shared/components/ui/RecordSummary.jsx');
    const {translate} = await vite.ssrLoadModule('/src/shared/lib/i18n.js');
    const product={id:'p-1',name:{en:'Barilla 500g',ar:'باريلا 500غ'},sku:'SKU-001',gtin:'08076800195057',gtinDuplicate:true,price:'1.500',currency:'JOD'};
    for (const locale of ['en','ar']) {
      const t=(key,values)=>translate(locale,key,values);
      const render=node=>renderToStaticMarkup(React.createElement(MemoryRouter,null,node));
      const catalog=render(React.createElement(CatalogTable,{products:[product],t,locale}));
      assert.match(catalog,/08076800195057/);assert.match(catalog,/\/products\/p-1/);assert.match(catalog,/1.500 JOD/);
      assert.ok(catalog.includes(product.name[locale]));
      const props={t,locale,rows:[{id:'c1',name:'Retailer',isTracked:false,website:'https://retailer.example',addedAt:'2026-10-16'}],onDetails:()=>{},onTrack:()=>{}};
      const readonly=render(React.createElement(CompetitorTable,props));
      assert.ok(readonly.includes(t('competitorManagement.inactive')));
      assert.ok(!readonly.includes(t('competitorManagement.reactivate')));
      const editable=render(React.createElement(CompetitorTable,{...props,canEdit:true,canReactivate:true,busy:true}));
      assert.ok(editable.includes(t('competitorManagement.reactivate')));assert.match(editable,/disabled/);
      const empty=render(React.createElement(CatalogTable,{products:[],t,locale,filtered:true}));
      assert.ok(empty.includes(t('catalog.ux.noMatches')));assert.ok(empty.includes(t('catalog.ux.tryFilters')));
      assert.doesNotMatch(catalog+readonly+empty,/catalog\.ux\.|directoryUx\./);
    }
    const summary=renderToStaticMarkup(React.createElement(RecordSummary,{items:[{label:'Zero',value:0},{label:'Missing',value:null}]}));
    assert.match(summary,/<dd>0<\/dd>/);assert.match(summary,/<dd>—<\/dd>/);
  } finally {await vite.close();}
});

test('the actual catalog and competitor pages render with cached API-shaped records', async () => {
  const vite=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'});
  try {
    const {QueryClient,QueryClientProvider}=await import('@tanstack/react-query');
    const {Routes,Route}=await import('react-router-dom');
    const {I18nProvider}=await vite.ssrLoadModule('/src/app/providers/I18nProvider.jsx');
    const cases=[
      ['/products','/products','/src/features/products/pages/CatalogPage.jsx','CatalogPage','product-catalog',{products:[],pagination:{page:1,pages:1,total:0},canEdit:false,capacity:{currentUsage:0,limit:100}},/Products/],
      ['/products/p-1','/products/:productId','/src/features/products/pages/CatalogProductPage.jsx','CatalogProductPage','catalog-product',{product:{id:'p-1',name:{en:'Verified catalog product'},sku:'SKU-001',gtin:'08076800195057',price:'1.5',currency:'JOD'},inventory:{currentStock:0,levels:[]},priceHistory:[],canEdit:false},/Verified catalog product/],
      ['/market/competitors','/market/competitors','/src/features/market-intelligence/pages/CompetitorsPage.jsx','CompetitorsPage','competitors',{competitors:[],canEdit:false,capacity:{included:true,currentUsage:0,limit:5}},/Competitors in this view/],
      ['/market/competitors/c1','/market/competitors/:competitorId','/src/features/market-intelligence/pages/CompetitorProfileDetailPage.jsx','CompetitorProfileDetailPage','competitor-profile',{name:'Retailer fixture',isTracked:false,canEdit:false,mappedProducts:[],activity:[],sources:[]},/Confirmed matches/]
    ];
    for (const [url,path,module,name,prefix,data,expected] of cases) {
      const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}});
      const key=prefix==='product-catalog'?[prefix,null,{search:'',status:'active',sort:'name',page:1,pageSize:25}]:[prefix,null,prefix==='catalog-product'?'p-1':prefix==='competitor-profile'?'c1':'active'];
      client.setQueryData(key,data);
      const component=(await vite.ssrLoadModule(module))[name];
      const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(MemoryRouter,{initialEntries:[url]},React.createElement(I18nProvider,null,React.createElement(Routes,null,React.createElement(Route,{path,element:React.createElement(component)}))))));
      assert.match(html,expected,`${name} should render the actual page`);
      assert.doesNotMatch(html,/catalog\.ux\.|directoryUx\./);
      client.clear();
    }
  } finally {await vite.close();}
});

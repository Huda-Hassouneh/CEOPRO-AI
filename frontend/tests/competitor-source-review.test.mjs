import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';

test('real review form renders in English/Arabic, separates approval and hides privileged controls',async()=>{
 const vite=await createServer({server:{middlewareMode:true},appType:'custom'});
 try {
  const {CompetitorSourceReviews}=await vite.ssrLoadModule('/src/features/market-intelligence/components/CompetitorSourceReviews.jsx');
  const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  const source={id:'source',name:'Market fixture',url:'https://market.example/product/tea',policyStatus:'RESTRICTED',isActive:true,reviewSupported:true,mappedProducts:2,retentionDays:30,rateLimitPerMinute:10};
  const render=(locale,detail)=>{
   const client=new QueryClient();
   const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(CompetitorSourceReviews,{detail,tenantId:'tenant',competitorId:'competitor',t:(key,values)=>translate(locale,key,values),formatDate:()=> 'today'})));
   client.clear();return html;
  };
  const detail={canReviewSources:true,isTracked:true,sources:[source]};
  const en=render('en',detail),ar=render('ar',detail);
  assert.match(en,/Collection source review/);assert.match(ar,/مراجعة مصدر جمع البيانات/);
  assert.match(en,/Confirming an identical product and approving a collection source are separate/);
  assert.match(en,/Linked products in this competitor: 2/);assert.match(en,/Terms or permission evidence/);
  assert.match(en,/Terms permit collection/);assert.match(en,/Terms do not permit collection/);
  assert.match(en,/<button[^>]*type="submit"[^>]*disabled/,'Approval is disabled until evidence and privacy are supplied');
  const readonly=render('en',{...detail,canReviewSources:false});
  assert.doesNotMatch(readonly,/<form|<button/);assert.match(readonly,/workspace owner or source reviewer/);
  const unsupported=render('en',{...detail,sources:[{...source,reviewSupported:false}]});
  assert.doesNotMatch(unsupported,/<form/);
  assert.match(render('en',{...detail,isTracked:false}),/Resume competitor tracking/);
  assert.match(render('en',{...detail,sources:[{...source,isActive:false}]}),/Approval does not reactivate/);
  assert.doesNotMatch(en+ar,/sourceReview\.[\w.]+|\{\{count\}\}/,'No missing labels or uninterpolated placeholders');
 }finally{await vite.close();}
});

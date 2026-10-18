import test from 'node:test';
import assert from 'node:assert/strict';
import {collectionState} from '../src/features/market-intelligence/utils/collectionStatus.js';
import {createServer} from 'vite';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';

test('collection status separates delivery, execution, automatic retry, failure and stale reporting',()=>{
 const now=Date.now();
 assert.equal(collectionState(null),'NO_REQUEST');
 assert.equal(collectionState({status:'PENDING',worker_status:'QUEUED'}),'QUEUED');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'QUEUED',published_at:new Date(now).toISOString()},now),'SUBMITTED');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'QUEUED',published_at:new Date(now-3600000).toISOString()},now),'UNCONFIRMED');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'QUEUED',worker_error_code:'COLLECTION_RETRY_PENDING'},now),'RETRYING');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'RUNNING',worker_heartbeat_at:new Date(now).toISOString()},now),'RUNNING');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'RUNNING',worker_heartbeat_at:new Date(now-3600000).toISOString()},now),'INTERRUPTED');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'FAILED'}),'FAILED');
 assert.equal(collectionState({status:'PUBLISHED',worker_status:'COMPLETED'}),'COMPLETED');
 assert.equal(collectionState({status:'CANCELLED',worker_status:'RUNNING'}),'CANCELLED');
});
test('real retry control renders only for an authorized failed eligible source, in English and Arabic',async()=>{
 const vite=await createServer({server:{middlewareMode:true},appType:'custom'});
 try{
  const {CollectionStatus}=await vite.ssrLoadModule('/src/features/market-intelligence/components/CollectionStatus.jsx');
  const {translate}=await vite.ssrLoadModule('/src/shared/lib/i18n.js');
  const source={id:'source',canRetryCollection:true,collection:{event_id:'failed-event',status:'PUBLISHED',worker_status:'FAILED',worker_error_code:'COLLECTION_RETRIES_EXHAUSTED',worker_attempts:3}};
  const render=(locale,props={})=>{
   const client=new QueryClient();const html=renderToStaticMarkup(React.createElement(QueryClientProvider,{client},React.createElement(CollectionStatus,{source,detail:{canEdit:true},tenantId:'tenant',competitorId:'competitor',t:(key,values)=>translate(locale,key,values),...props})));client.clear();return html;
  };
  assert.match(render('en'),/Retry failed collection/);assert.match(render('ar'),/إعادة محاولة الجمع الفاشل/);
  assert.match(render('en'),/Collection attempts: 3/);
  assert.doesNotMatch(render('en',{detail:{canEdit:false}}),/<button/);
  assert.doesNotMatch(render('en',{source:{...source,canRetryCollection:false}}),/<button/);
  assert.doesNotMatch(render('en',{source:{...source,collection:{...source.collection,worker_status:'RUNNING'}}}),/<button/);
  assert.doesNotMatch(render('ar')+render('en'),/collectionTracking\.[\w.]+|\{\{count\}\}/);
 }finally{await vite.close();}
});

import assert from 'node:assert/strict';
import test from 'node:test';
import { saveWebsiteSource, normalizeWebsiteUrl } from '../src/features/onboarding/utils/saveWebsiteSource.js';

test('backend configured response saves website without a connected boolean',async()=>{
  let payload;
  const result=await saveWebsiteSource(' https://store.example.com/ ',{configureWebsite:async value=>{payload=value;return {id:'source-1',connectionStatus:'configured',isActive:true,sourceUrl:'https://store.example.com'};}});
  assert.deepEqual(payload,{url:'https://store.example.com'});
  assert.deepEqual(result,{id:'source-1',url:'https://store.example.com',status:'configured'});
});
test('invalid URL is rejected before making a request',async()=>{
  for(const url of ['', 'store.example.com','ftp://store.example.com','https://user:password@store.example.com']){
    await assert.rejects(()=>saveWebsiteSource(url,{configureWebsite:async()=>assert.fail('Invalid URL must not make an API request')}),error=>error.code==='INVALID_WEBSITE_URL');
  }
  assert.equal(normalizeWebsiteUrl('https://store.example.com/products///#section'),'https://store.example.com/products');
});
test('malformed and disconnected responses cannot report successful setup',async()=>{
  for(const source of [{},{id:'one',connected:true},{id:'one',connectionStatus:'disconnected'},{id:'one',connectionStatus:'configured',isActive:false}]){
    await assert.rejects(()=>saveWebsiteSource('https://store.example.com',{configureWebsite:async()=>source}),error=>error.code==='WEBSITE_SAVE_FAILED');
  }
});
test('permission, capacity and network errors retain their original details',async()=>{
  for(const error of [{response:{status:403,data:{error:{code:'FEATURE_NOT_INCLUDED',message:'Not included'}}}},{response:{status:409,data:{error:{code:'USAGE_EXCEEDED',message:'Limit reached'}}}},{request:{},message:'Network Error'}]){
    await assert.rejects(()=>saveWebsiteSource('https://store.example.com',{configureWebsite:async()=>{throw error;}}),caught=>caught===error);
  }
});
test('duplicate from an earlier false warning reuses the tenant-owned active website',async()=>{
  const duplicate={response:{data:{error:{code:'DUPLICATE_RESOURCE'}}}};
  const result=await saveWebsiteSource('https://store.example.com/',{configureWebsite:async()=>{throw duplicate;},list:async()=>({connectedSources:[{id:'existing',type:'website',isActive:true,status:'not synced',sourceUrl:'https://store.example.com'}]})});
  assert.equal(result.id,'existing');assert.equal(result.status,'configured');
});
test('duplicate recovery does not reactivate a paused or disconnected website',async()=>{
  const duplicate={response:{data:{error:{code:'DUPLICATE_RESOURCE'}}}};
  for(const source of [{id:'inactive',type:'website',isActive:false,status:'paused',sourceUrl:'https://store.example.com'},{id:'disconnected',type:'website',isActive:true,status:'disconnected',sourceUrl:'https://store.example.com'},{id:'different',type:'website',isActive:true,status:'not synced',sourceUrl:'https://other.example.com'}]){
    await assert.rejects(()=>saveWebsiteSource('https://store.example.com',{configureWebsite:async()=>{throw duplicate;},list:async()=>({connectedSources:[source]})}),error=>error===duplicate);
  }
});

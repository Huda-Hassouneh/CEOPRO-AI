import test from 'node:test';
import assert from 'node:assert/strict';
import {discoveryState} from '../src/features/market-intelligence/utils/discoveryStatus.js';
test('discovery distinguishes delivery, execution, terminal states and overdue heartbeats',()=>{
 assert.equal(discoveryState({status:'PUBLISHED',worker_status:'QUEUED'}),'QUEUED');
 assert.equal(discoveryState({status:'PENDING',worker_status:'CANCELLED'}),'CANCELLED');
 assert.equal(discoveryState({status:'CANCELLED',worker_status:'RUNNING'}),'CANCELLED');
 assert.equal(discoveryState({status:'PUBLISHED',worker_status:'RUNNING',worker_heartbeat_at:new Date(10000)},10001),'RUNNING');
 assert.equal(discoveryState({status:'PUBLISHED',worker_status:'RUNNING',worker_heartbeat_at:new Date(10000)},100001),'INTERRUPTED');
 for(const state of ['COMPLETED','NO_MATCHES','PARTIAL','TIMED_OUT','FAILED'])assert.equal(discoveryState({status:'PUBLISHED',worker_status:state}),state);
});

test('HTTP denial, rules denial and unavailable discovery are distinct from no matches',()=>{
 for(const [code,state] of [['HTTP_ACCESS_DENIED','ACCESS_DENIED'],['ROBOTS_DISALLOWED','ROBOTS_DISALLOWED'],['ROBOTS_UNAVAILABLE','UNAVAILABLE'],['HTTP_RATE_LIMITED','UNAVAILABLE'],['CONTENT_UNAVAILABLE','UNAVAILABLE'],['NO_DISCOVERY_METHOD','UNAVAILABLE']]){
  assert.equal(discoveryState({status:'PUBLISHED',worker_status:'FAILED',worker_error_code:code}),state);
 }
 assert.equal(discoveryState({status:'PUBLISHED',worker_status:'NO_MATCHES'}),'NO_MATCHES');
});

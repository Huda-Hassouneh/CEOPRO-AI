import test from 'node:test';
import assert from 'node:assert/strict';
import {resolve} from 'node:path';
import {checkSourceRobots} from '../../src/modules/competitors/client/source-review.client.ts';

test('real Node-to-Python checker transport rejects private targets and fails closed on configuration/startup errors',async()=>{
 const saved={path:process.env.MARKET_AI_CODEBASE_PATH,python:process.env.MARKET_AI_PYTHON};
 try {
  delete process.env.MARKET_AI_CODEBASE_PATH;
  assert.deepEqual(await checkSourceRobots(['http://127.0.0.1/product/tea']),{allowed:null,reason:'CHECKER_NOT_CONFIGURED'});
  process.env.MARKET_AI_CODEBASE_PATH=resolve('../ai');
  process.env.MARKET_AI_PYTHON=process.env.KEEL_TEST_PYTHON || (process.platform==='win32'?'python':'python3');
  assert.deepEqual(await checkSourceRobots(['http://127.0.0.1/product/tea']),{allowed:false,reason:'UNSAFE_TARGET'});
  process.env.MARKET_AI_PYTHON=resolve('missing-source-review-python-executable');
  assert.deepEqual(await checkSourceRobots(['http://127.0.0.1/product/tea']),{allowed:null,reason:'CHECKER_UNAVAILABLE'});
 } finally {
  if(saved.path===undefined)delete process.env.MARKET_AI_CODEBASE_PATH;else process.env.MARKET_AI_CODEBASE_PATH=saved.path;
  if(saved.python===undefined)delete process.env.MARKET_AI_PYTHON;else process.env.MARKET_AI_PYTHON=saved.python;
 }
});

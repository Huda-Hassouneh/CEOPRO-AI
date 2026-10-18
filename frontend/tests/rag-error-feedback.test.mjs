import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {getRagErrorFeedback} from '../src/features/knowledge-base/utils/ragErrorFeedback.js';

const apiError=(code,details,status=400)=>({response:{status,data:{error:{code,details}}}});
for(const locale of ['en','ar']) {
  const messages=JSON.parse(readFileSync(new URL(`../src/assets/locales/${locale}.json`,import.meta.url)));
  const t=key=>key.split('.').reduce((value,part)=>value?.[part],messages);
  const feedback=error=>getRagErrorFeedback(error,{action:'chat',t,locale});
  test(`${locale}: empty knowledge base has an actionable message on old and new servers`,()=>{
    for(const details of [
      {reason:'NO_DOCUMENTS',message:'No readable documents'},
      'Upload at least one processed RAG document before asking a question.'
    ])assert.deepEqual(feedback(apiError('INVALID_REQUEST',details)),{
      variant:'info',message:t('ragAssistant.errors.noDocuments')
    });
    assert.ok(t('ragAssistant.errors.noDocuments'));
  });
  test(`${locale}: validation, authentication, quota, and outages remain distinct`,()=>{
    for(const [code,status,key] of [
      ['VALIDATION_ERROR',400,'invalidQuestion'],
      ['UNAUTHORIZED',401,'sessionExpired'],
      ['PAYMENT_REQUIRED',402,'ragQuotaReached'],
      ['EXTERNAL_SERVICE_ERROR',502,'serviceUnavailable']
    ])assert.equal(feedback(apiError(code,null,status)).message,t(`ragAssistant.errors.${key}`));
    assert.equal(feedback({code:'ERR_NETWORK'}).message,t('ragAssistant.errors.network'));
  });
  test(`${locale}: a PDF processor failure does not accuse the customer file`,()=>{
    const result=getRagErrorFeedback(apiError('SERVICE_UNAVAILABLE',{
      reason:'DOCUMENT_PROCESSING_UNAVAILABLE'
    },503),{action:'upload',t,locale});
    assert.equal(result.message,t('ragAssistant.errors.documentProcessingUnavailable'));
    assert.ok(result.message);
    assert.notEqual(result.message,t('ragAssistant.errors.invalidFile'));
  });
}

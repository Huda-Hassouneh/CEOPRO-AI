import {useState} from 'react';
import {useMutation,useQueryClient} from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import {getApiErrorMessage} from '../../../shared/lib/apiErrors.js';
import {competitorsApi} from '../api/competitorsApi.js';
import {collectionState} from '../utils/collectionStatus.js';
export function CollectionStatus({source,detail,competitorId,tenantId,t,locale='en'}) {
  const cache=useQueryClient(),[notice,setNotice]=useState('');
  const event=source.collection,state=collectionState(event);
  const requested=event?.created_at && Number.isFinite(new Date(event.created_at).getTime())?new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short'}).format(new Date(event.created_at)):null;
  const retry=useMutation({mutationFn:()=>competitorsApi.retryCollection(competitorId,source.id,event.event_id),onSuccess:async result=>{
    setNotice(t(result.created?'collectionTracking.retryQueued':'collectionTracking.existingRetry'));
    await cache.invalidateQueries({queryKey:['competitor-profile',tenantId,competitorId]});
  }});
  return <div className="competitor-collection-status">
    <strong>{t('collectionTracking.title')}</strong><p role="status">{t(`collectionTracking.states.${state}`)}</p>
    {requested && <p>{t('collectionTracking.requested',{date:requested})}</p>}
    {state==='COMPLETED' && Number.isInteger(event?.worker_result?.rows_processed) && <p>{t('collectionTracking.rows',{processed:event.worker_result.rows_processed,failed:event.worker_result.rows_failed ?? 0,quarantined:event.worker_result.rows_quarantined ?? 0})}</p>}
    {event?.worker_error_code && <p>{t(`collectionTracking.errors.${event.worker_error_code}`)}</p>}
    {event?.worker_attempts>0 && <p>{t('collectionTracking.attempts',{count:event.worker_attempts})}</p>}
    {detail.canEdit && source.canRetryCollection && state==='FAILED' && <Button variant="outline" disabled={retry.isPending} onClick={()=>{setNotice('');retry.mutate();}}>{t(retry.isPending?'collectionTracking.retrying':'collectionTracking.retry')}</Button>}
    {retry.error && <p role="alert">{getApiErrorMessage(retry.error,t)}</p>}
    {notice && <p role="status">{notice}</p>}
  </div>;
}

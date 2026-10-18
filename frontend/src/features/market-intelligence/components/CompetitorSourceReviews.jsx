import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import {CollectionStatus} from './CollectionStatus.jsx';
import {collectionState} from '../utils/collectionStatus.js';
import {useState} from 'react';
import {useMutation,useQueryClient} from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import {getApiErrorMessage} from '../../../shared/lib/apiErrors.js';
import {competitorsApi} from '../api/competitorsApi.js';

function SourceReview({source,detail,competitorId,tenantId,t,formatDate,locale}) {
  const cache=useQueryClient();
  const [reference,setReference]=useState('');
  const [privacy,setPrivacy]=useState(false);
  const [personal,setPersonal]=useState(source.containsPersonalData ?? false);
  const [retention,setRetention]=useState(source.retentionDays ?? 30);
  const [rate,setRate]=useState(Math.min(30,source.rateLimitPerMinute ?? 10));
  const [notice,setNotice]=useState(null);
  const mutation=useMutation({mutationFn:termsPermit=>competitorsApi.reviewSource(competitorId,source.id,{
    termsPermit,reference:reference.trim(),privacyReviewed:privacy,containsPersonalData:personal,
    retentionDays:Number(retention),rateLimitPerMinute:Number(rate)
  }),onSuccess:async result=>{
    setNotice(result);
    await cache.invalidateQueries({queryKey:['competitor-profile',tenantId,competitorId]});
  }});
  const reasonKey=`sourceReview.reasons.${source.reason}`;
  const reasonLabel=source.reason ? t(reasonKey) : '';
  const allowed=detail.canReviewSources && source.reviewSupported;
  const valid=reference.trim().length>=10 && Number(retention)>=1 && Number(retention)<=90 && Number.isInteger(Number(retention)) && Number(rate)>=1 && Number(rate)<=30 && Number.isInteger(Number(rate));
  return <details className="competitor-source-review">
    <summary><strong>{source.name}</strong><span>{t(`sourceReview.status.${source.policyStatus}`)}</span> · <span>{t(`collectionTracking.states.${collectionState(source.collection)}`)}</span></summary>
    {source.url && <a href={source.url} target="_blank" rel="noopener noreferrer">{source.url}</a>}
    <p>{t('sourceReview.mappingCount',{count:source.mappedProducts})}</p>
    {source.checkedAt && <p>{t('sourceReview.lastReview',{date:formatDate(source.checkedAt)})}</p>}
    {source.reason && <p>{reasonLabel===reasonKey?source.reason:reasonLabel}</p>}
    {source.approvalReference && <p className="competitor-source-reference">{source.approvalReference}</p>}
    {!source.isActive && <p>{t('sourceReview.inactive')}</p>}
    {!source.reviewSupported && <p>{t('sourceReview.unsupported')}</p>}
    {!detail.canReviewSources && <p>{t('sourceReview.noPermission')}</p>}
    <CollectionStatus source={source} detail={detail} competitorId={competitorId} tenantId={tenantId} t={t} locale={locale} />
    {allowed && <form onSubmit={event=>{event.preventDefault();setNotice(null);mutation.mutate(true);}}>
      <p>{t('sourceReview.evidenceHint')}</p>
      <Input label={t('sourceReview.reference')} value={reference} minLength={10} maxLength={2000} required onChange={e=>setReference(e.target.value)} disabled={mutation.isPending} />
      <div className="competitor-source-fields">
        <Input label={t('sourceReview.retention')} type="number" min="1" max="90" step="1" required value={retention} onChange={e=>setRetention(e.target.value)} disabled={mutation.isPending} />
        <Input label={t('sourceReview.rate')} type="number" min="1" max="30" step="1" required value={rate} onChange={e=>setRate(e.target.value)} disabled={mutation.isPending} />
      </div>
      <label><input type="checkbox" checked={personal} onChange={e=>setPersonal(e.target.checked)} disabled={mutation.isPending} /> {t('sourceReview.personal')}</label>
      <label><input type="checkbox" checked={privacy} onChange={e=>setPrivacy(e.target.checked)} disabled={mutation.isPending} /> {t('sourceReview.privacy')}</label>
      <div className="competitor-management-actions">
        <Button type="submit" disabled={!detail.isTracked || !valid || !privacy || mutation.isPending}>{t(mutation.isPending?'sourceReview.checking':'sourceReview.approve')}</Button>
        <Button type="button" variant="outline" disabled={!valid || mutation.isPending} onClick={()=>{setNotice(null);mutation.mutate(false);}}>{t('sourceReview.reject')}</Button>
      </div>
      {!detail.isTracked && <p>{t('sourceReview.trackFirst')}</p>}
    </form>}
    {mutation.error && <p role="alert" className="competitor-feedback competitor-feedback--error">{getApiErrorMessage(mutation.error,t)}</p>}
    {notice && <div role="status" className="competitor-feedback">
      <p>{t(`sourceReview.status.${notice.policyStatus}`)} · {t(`sourceReview.reasons.${notice.technicalReason}`)}</p>
      {notice.policyStatus==='ALLOWED' && <p>{notice.collection.existingRequest?t('sourceReview.existingCollection'):notice.collection.reason==='QUEUED'?t(notice.collection.configured?'sourceReview.queued':'sourceReview.awaitingSetup'):t(`sourceReview.reasons.${notice.collection.reason}`)}</p>}
    </div>}
  </details>;
}
function ConnectedCompetitorSourceReviews(props) {
  const {detail,t}=props;
  return <section className="market-panel competitor-source-reviews" id="competitor-source-reviews">
    <h2>{t('sourceReview.title')}</h2><p>{t('sourceReview.hint')}</p>
    {!detail.sources?.length && <p>{t('sourceReview.empty')}</p>}
    {detail.sources?.map(source=><SourceReview key={source.id} source={source} {...props} />)}
  </section>;
}

// Do not mount queries or forms for the withdrawn worker contract.
export function CompetitorSourceReviews(props) { return COMPETITOR_AI_ACTIONS_ENABLED ? <ConnectedCompetitorSourceReviews {...props} /> : null; }

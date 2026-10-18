import {Link} from 'react-router-dom';
import {routePaths} from '../../app/router/routePaths.js';
import {useRef,useState} from 'react';
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {useAuthStore} from '../auth/store/authStore.js';
import {useI18n} from '../../app/providers/I18nProvider.jsx';
import PageHeader from '../../shared/components/layout/PageHeader.jsx';
import Button from '../../shared/components/ui/Button.jsx';
import EmptyState from '../../shared/components/ui/EmptyState.jsx';
import {recommendationsApi} from './api.js';
import {RecommendationEvidence} from './RecommendationEvidence.jsx';
export function BusinessRecommendationsPage(){
 const {t,locale,dir}=useI18n(),client=useQueryClient();
 const tenant=useAuthStore(s=>s.tenantId),user=useAuthStore(s=>s.user?.id??s.user?.user_id);
 const scope=tenant+':'+user,[state,setState]=useState('active'),[page,setPage]=useState(1),retry=useRef(null),flight=useRef(false);
 const query=useQuery({queryKey:['business-recommendations',tenant,user,state,page],queryFn:({signal})=>recommendationsApi.list(state,page,signal),enabled:Boolean(tenant&&user),retry:false});
 const invalidate=()=>client.invalidateQueries({queryKey:['business-recommendations']});
 const refresh=useMutation({mutationFn:({requestId})=>recommendationsApi.refresh(requestId),retry:false,onSuccess:()=>{retry.current=null;invalidate();},onError:error=>{
  const reason=error.response?.data?.error?.details?.reason;
  if(error.response&&reason!=='REQUEST_PENDING')retry.current=null;
 }});
 const change=useMutation({mutationFn:({id,state})=>recommendationsApi.state(id,state),onSuccess:invalidate,retry:false});
 const run=()=>{if(flight.current||refresh.isPending)return;flight.current=true;
  const requestId=retry.current?.scope===scope?retry.current.id:crypto.randomUUID();retry.current={scope,id:requestId};
  refresh.mutate({requestId,scope},{onSettled:()=>{flight.current=false;}});
 };
 const error=refresh.isError&&refresh.variables?.scope===scope?refresh.error:change.error??query.error;
 const reason=error?.response?.data?.error?.details?.reason;
 const message=reason==='REQUEST_PENDING'?t('businessRecommendations.pending'):reason==='REQUEST_FAILED'||reason==='REQUEST_EXPIRED'?t('businessRecommendations.requestFailed'):
  error?.response?.status===403?t('businessRecommendations.forbidden'):t('businessRecommendations.unavailable');
 const entries=query.data?.recommendations??[];
 return <div dir={dir} className="market-intelligence-main">
  <PageHeader title={t('businessRecommendations.title')} subtitle={t('businessRecommendations.subtitle')} actions={<Button onClick={run} disabled={refresh.isPending}>{t(refresh.isPending?'businessRecommendations.refreshing':'businessRecommendations.refresh')}</Button>}/>
  <p>{t('businessRecommendations.sourcePolicy')}</p>
  <label>{t('businessRecommendations.filter')}{' '}<select className="market-main-select" value={state} onChange={e=>{setState(e.target.value);setPage(1);}}>
   {['active','dismissed','resolved','all'].map(s=><option key={s} value={s}>{t('businessRecommendations.states.'+s)}</option>)}
  </select></label>
  {error&&<p role="alert">{message}{' '}<Button size="sm" variant="outline" onClick={()=>query.refetch()}>{t('businessRecommendations.retry')}</Button></p>}
  {query.isPending?<p role="status">{t('businessRecommendations.loading')}</p>:!query.isError&&!entries.length?<EmptyState title={t('businessRecommendations.emptyTitle')} description={t('businessRecommendations.emptyDescription')}/>:null}
  {refresh.data&&refresh.variables?.scope===scope&&!refresh.data.complete&&<p role="status">{t('businessRecommendations.partial')}</p>}
  {entries.map(r=>{const body=r.body??{},names=body.product_name,name=typeof names==='object'&&names?names[locale]??names.en: names;
   return <article className="dashboard-panel" key={r.recommendation_id}>
    <h2>{r.product_id?<Link to={routePaths.productDetail.replace(':productId',encodeURIComponent(r.product_id))}>{name||t('businessRecommendations.businessWide')}</Link>:name||t('businessRecommendations.businessWide')}</h2>
    <p>{t('businessRecommendations.categories.'+r.category)}{' · '}{t('businessRecommendations.priorities.'+r.priority)}{' · '}{t('businessRecommendations.states.'+r.state)}</p>
    <p>{body.message_i18n?.[locale]??body.message}</p>
    <p>{t('businessRecommendations.asOf',{date:new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short'}).format(new Date(r.last_seen_at))})}</p>
    <RecommendationEvidence evidence={body.evidence} t={t} locale={locale}/>
    {query.data.can_manage&&r.state!=='resolved'&&<Button size="sm" variant="outline" disabled={change.isPending} onClick={()=>change.mutate({id:r.recommendation_id,state:r.state==='dismissed'?'active':'dismissed'})}>{t(r.state==='dismissed'?'businessRecommendations.restore':'businessRecommendations.dismiss')}</Button>}
   </article>;
  })}
  <div><Button size="sm" variant="outline" disabled={page<=1||query.isFetching} onClick={()=>setPage(p=>p-1)}>{t('businessRecommendations.previous')}</Button>{' '}
   <span>{page}</span>{' '}<Button size="sm" variant="outline" disabled={query.isFetching||page*20>=(query.data?.total??0)} onClick={()=>setPage(p=>p+1)}>{t('businessRecommendations.next')}</Button></div>
 </div>;
}

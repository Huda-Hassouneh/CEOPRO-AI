import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import {useEffect,useState} from 'react';
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import {getApiErrorMessage} from '../../../shared/lib/apiErrors.js';
import {competitorsApi} from '../api/competitorsApi.js';
import {CompetitorConfirmation} from './CompetitorConfirmation.jsx';
import {ProductIdentityEvidence} from './ProductIdentityEvidence.jsx';

function ConnectedCompetitorProductLinks({detail,competitorId,tenantId,t,locale}) {
  const cache=useQueryClient();
  const [search,setSearch]=useState(''),[term,setTerm]=useState(''),[page,setPage]=useState(1);
  const [productId,setProductId]=useState(''),[url,setUrl]=useState(''),[pending,setPending]=useState(null);
  const [notice,setNotice]=useState('');
  useEffect(()=>{const timer=setTimeout(()=>{setTerm(search);setPage(1);},250);return()=>clearTimeout(timer);},[search]);
  const catalog=useQuery({queryKey:['competitor-catalog',tenantId,competitorId,term,page],
    queryFn:({signal})=>competitorsApi.catalog(competitorId,{search:term,page},signal),enabled:detail.canEdit && detail.isTracked});
  const products=catalog.data?.products||[];
  const selected=products.find(product=>product.id===productId);
  const candidates=useQuery({queryKey:['competitor-candidates',tenantId,competitorId,productId],
    queryFn:({signal})=>competitorsApi.productCandidates(competitorId,productId,signal),enabled:!!productId});
  useEffect(()=>{setProductId('');setUrl('');},[term,page]);
  useEffect(()=>{setUrl(selected?.url||'');},[productId,selected?.url]);
  const mutation=useMutation({mutationFn:action=>action.type==='reject'
    ?competitorsApi.rejectCandidate(competitorId,action.candidateId)
    :action.type==='preview'?competitorsApi.previewProduct(competitorId,action.mappingId)
    :competitorsApi.linkProduct(competitorId,action.payload),onSuccess:async(result,action)=>{
      setPending(null);setNotice(t(action.type==='preview'?'competitorWorkflow.previewSaved':action.type==='reject'?'competitorWorkflow.rejected':'competitorWorkflow.linkSaved'));
      await Promise.all([cache.invalidateQueries({queryKey:['competitor-profile',tenantId,competitorId]}),cache.invalidateQueries({queryKey:['competitor-catalog',tenantId,competitorId]}),cache.invalidateQueries({queryKey:['competitor-candidates',tenantId,competitorId]})]);
    }});
  const save=event=>{
    event.preventDefault();setNotice('');
    const payload={productId,url:url.trim(),expectedMappingId:selected?.mappingId??null};
    if(selected?.mappingId && selected.url!==payload.url)setPending(payload);
    else mutation.mutate({type:'link',payload});
  };
  return <section className="market-panel competitor-product-links" id="competitor-product-links">
    <h2>{t('competitorWorkflow.title')}</h2><p>{t('competitorWorkflow.flow')}</p>
    {detail.canEdit && detail.isTracked && <>
      <form onSubmit={save}>
        <Input label={t('competitorWorkflow.search')} value={search} maxLength={150} onChange={e=>setSearch(e.target.value)} />
        <Select label={t('competitorWorkflow.yourProduct')} value={productId} onChange={e=>setProductId(e.target.value)}
          options={[{value:'',label:t('competitorWorkflow.choose')},...products.map(product=>({value:product.id,label:typeof product.name==='string'?product.name:product.name?.[locale]||product.name?.en||product.name?.ar||product.id}))]} />
        <div className="competitor-management-actions">
          <Button type="button" variant="outline" disabled={page===1||catalog.isFetching} onClick={()=>setPage(value=>value-1)}>{t('competitorWorkflow.previous')}</Button>
          <Button type="button" variant="outline" disabled={!catalog.data?.hasMore||catalog.isFetching} onClick={()=>setPage(value=>value+1)}>{t('competitorWorkflow.next')}</Button>
        </div>
        {catalog.error && <p role="alert">{getApiErrorMessage(catalog.error,t)}</p>}
        <Input label={t('competitorWorkflow.productUrl')} type="url" required value={url} maxLength={2048} onChange={e=>setUrl(e.target.value)} hint={t('competitorWorkflow.urlScope')} />
        <Button type="submit" disabled={!selected||!url.trim()||mutation.isPending}>{t('competitorWorkflow.saveLink')}</Button>
      </form>
      {selected && <div className="competitor-candidate-list">
        <h3>{t('competitorWorkflow.alternatives')}</h3><p>{t('competitorWorkflow.candidateHint')}</p>
        {(candidates.data||[]).map(candidate=><div key={candidate.candidate_id} className="competitor-candidate-row">
          <a href={candidate.product_url} target="_blank" rel="noopener noreferrer">{candidate.title||candidate.product_url}</a>
          <div className="competitor-management-actions">
            <Button type="button" variant="outline" disabled={mutation.isPending||candidate.product_url===selected.url} onClick={()=>setUrl(candidate.product_url)}>{t('competitorWorkflow.useUrl')}</Button>
            <Button type="button" variant="outline" disabled={mutation.isPending} onClick={()=>mutation.mutate({type:'reject',candidateId:candidate.candidate_id})}>{t('competitorWorkflow.reject')}</Button>
          </div>
        </div>)}
      </div>}
    </>}
    {detail.mappedProducts.map(item=><details key={item.mappingId} className="competitor-evidence-row">
      <summary>{typeof item.name==='string'?item.name:item.name?.[locale]||item.name?.en||item.name?.ar} · {t(item.comparisonConfirmed?'competitorWorkflow.confirmed':'competitorWorkflow.needsConfirmation')}</summary>
      <ProductIdentityEvidence identity={item.ownIdentity||{name:item.name}} preview={item.preview} t={t} locale={locale} />
      <a href={item.url||undefined} target="_blank" rel="noopener noreferrer">{item.url}</a>
      {detail.canEdit && detail.isTracked && <>
        <Button type="button" variant="outline" disabled={mutation.isPending||item.monitoring?.policyStatus!=='ALLOWED'||!item.monitoring?.isActive}
          onClick={()=>{setNotice('');mutation.mutate({type:'preview',mappingId:item.mappingId});}}>{t('competitorWorkflow.checkPage')}</Button>
        {item.monitoring?.policyStatus!=='ALLOWED' && <p><a href="#competitor-source-reviews">{t('competitorWorkflow.approveFirst')}</a></p>}
      </>}
    </details>)}
    {!!detail.previousMappings?.length && <details className="competitor-evidence-row"><summary>{t('competitorWorkflow.history')}</summary>
      <p>{t('competitorWorkflow.historyHint')}</p>
      {detail.previousMappings.map(mapping=><p key={mapping.mapping_id}><a href={mapping.competitor_product_url||undefined} target="_blank" rel="noopener noreferrer">{mapping.competitor_product_url}</a> · {t('competitorWorkflow.historyPrices',{count:mapping._count?.competitor_prices??0})}</p>)}
    </details>}
    {notice && <p role="status">{notice}</p>}
    {mutation.error && <p role="alert" className="competitor-feedback competitor-feedback--error">{getApiErrorMessage(mutation.error,t)}</p>}
    <CompetitorConfirmation open={!!pending} t={t} locale={locale} name={selected?.name?.[locale]||selected?.name?.en||''} message={t('competitorWorkflow.replaceWarning')}
      busy={mutation.isPending} error={mutation.error&&getApiErrorMessage(mutation.error,t)} onCancel={()=>setPending(null)} onConfirm={()=>mutation.mutate({type:'link',payload:pending})} />
  </section>;
}

// Do not mount queries or forms for the withdrawn worker contract.
export function CompetitorProductLinks(props) { return COMPETITOR_AI_ACTIONS_ENABLED ? <ConnectedCompetitorProductLinks {...props} /> : null; }

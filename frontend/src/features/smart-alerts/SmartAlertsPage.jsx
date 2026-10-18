import {COMPETITOR_AI_ACTIONS_ENABLED} from '../market-intelligence/config/competitorCapabilities.js';
import {useEffect,useState} from 'react';
import {useQuery,useMutation,useQueryClient} from '@tanstack/react-query';
import {ArrowDownRight,ArrowUpRight,BellRing,Check,CheckCheck,Clock3,RefreshCw,SlidersHorizontal} from 'lucide-react';
import {useI18n} from '../../app/providers/I18nProvider.jsx';
import {useAuthStore} from '../auth/store/authStore.js';
import http from '../../shared/lib/httpClient.js';
import PageHeader from '../../shared/components/layout/PageHeader.jsx';
import Button from '../../shared/components/ui/Button.jsx';
import EmptyState from '../../shared/components/ui/EmptyState.jsx';
import './SmartAlertsPage.css';

const base='/features/smart-alerts';
const initialRule={name:'',global_competitor_id:'',operator:'LTE',threshold:-5,cooldown_minutes:60,is_active:true};
const states=['open','acknowledged','resolved','all'];
const statusOf=event=>event.resolved_at?'resolved':event.acknowledged_at?'acknowledged':'open';

export function AlertEvent({event,canManage,action,t,locale}){
 const status=statusOf(event),change=Number(event.observed_value);
 const direction=Number.isFinite(change)?change<0?'down':change>0?'up':'steady':'steady';
 const changeText=Number.isFinite(change)?`${change>0?'+':''}${new Intl.NumberFormat(locale,{maximumFractionDigits:2}).format(change)}%`:t('smartAlerts.changeUnavailable');
 const when=value=>{const parsed=new Date(value);return Number.isNaN(parsed.getTime())?'—':new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short'}).format(parsed);};
 const busy=action.isPending&&action.variables?.id===event.alert_event_id;
 const title=event.trigger_facts?.name??event.market_alert_rules?.name??t('smartAlerts.title');
 const oldPrice=event.market_events?.old_value?.price,newPrice=event.market_events?.new_value?.price;
 return <article className={`smart-alerts__event dashboard-panel is-${status}`} aria-labelledby={`alert-${event.alert_event_id}`}>
  <div className="smart-alerts__event-main">
   <span className={`smart-alerts__direction is-${direction}`} aria-hidden="true">{direction==='down'?<ArrowDownRight size={22}/>:direction==='up'?<ArrowUpRight size={22}/>:<BellRing size={20}/>}</span>
   <div className="smart-alerts__event-content">
    <div className="smart-alerts__event-heading"><h3 id={`alert-${event.alert_event_id}`}>{title}</h3><span className={`smart-alerts__status is-${status}`}><span aria-hidden="true"/>{t(`smartAlerts.states.${status}`)}</span></div>
    <div className="smart-alerts__event-summary"><strong className={`smart-alerts__change is-${direction}`} dir="ltr">{changeText}</strong><span>{t('smartAlerts.priceChange')}</span></div>
    <time className="smart-alerts__timestamp" dateTime={event.created_at}><Clock3 size={14} aria-hidden="true"/>{when(event.created_at)}</time>
   </div>
  </div>
  {event.market_events&&<details className="smart-alerts__evidence"><summary>{t('smartAlerts.evidence')}</summary><div className="smart-alerts__evidence-content"><p>{t('smartAlerts.observed',{date:when(event.market_events.occurred_at)})}</p>{oldPrice!=null&&newPrice!=null&&<p><bdi>{oldPrice} → {newPrice} {event.market_events.new_value?.currency??''}</bdi></p>}<p>{t('smartAlerts.ruleAtTrigger')}</p></div></details>}
  {canManage&&status!=='resolved'&&<div className="smart-alerts__event-actions">{status==='open'&&<Button size="sm" leadingIcon={<Check size={16}/>} disabled={action.isPending} loading={busy&&action.variables?.action==='acknowledge'} onClick={()=>action.mutate({id:event.alert_event_id,action:'acknowledge'})}>{t('smartAlerts.acknowledge')}</Button>}<Button size="sm" variant="outline" leadingIcon={<CheckCheck size={16}/>} disabled={action.isPending} loading={busy&&action.variables?.action==='resolve'} onClick={()=>action.mutate({id:event.alert_event_id,action:'resolve'})}>{t('smartAlerts.resolve')}</Button></div>}
 </article>;
}

function ConnectedSmartAlertsPage(){
 const {t,locale,dir}=useI18n(),client=useQueryClient(),tenant=useAuthStore(s=>s.tenantId),user=useAuthStore(s=>s.user?.id??s.user?.user_id);
 const [state,setState]=useState('open'),[page,setPage]=useState(1),[form,setForm]=useState(initialRule),[edit,setEdit]=useState(null);
 const key=['smart-alerts',tenant,user];
 const query=useQuery({queryKey:[...key,state,page],enabled:Boolean(tenant&&user),queryFn:async({signal})=>(await http.get(base,{params:{state,page},signal})).data.data,retry:false,refetchInterval:30000});
 const refresh=()=>client.invalidateQueries({queryKey:key});
 const save=useMutation({mutationFn:async()=>edit?http.patch(base+'/rules/'+edit,form):http.post(base+'/rules',form),retry:false,onSuccess:()=>{setForm(initialRule);setEdit(null);refresh();}});
 const action=useMutation({mutationFn:({id,action})=>http.post(base+'/events/'+id+'/'+action),retry:false,onSuccess:refresh});
 const data=query.data,events=data?.events??[],rules=data?.rules??[],total=data?.total??0;
 useEffect(()=>{if(data&&!query.isFetching&&page>1&&events.length===0)setPage(Math.max(1,Math.ceil(total/20)));},[data,query.isFetching,page,events.length,total]);
 useEffect(()=>{if(edit)document.getElementById('smart-alerts-rule-name')?.focus();},[edit]);
 const formatCount=value=>new Intl.NumberFormat(locale).format(value);
 const resetForm=()=>{setEdit(null);setForm(initialRule);save.reset();};
 return <main className="market-intelligence-main smart-alerts" dir={dir}>
  <PageHeader title={t('smartAlerts.title')} subtitle={t('smartAlerts.subtitle')} actions={<Button variant="outline" leadingIcon={<RefreshCw size={16}/>} onClick={()=>query.refetch()} disabled={query.isFetching}>{t('smartAlerts.refresh')}</Button>}/>
  <section className="smart-alerts__feed" aria-labelledby="smart-alerts-feed-title">
   <div className="smart-alerts__section-heading"><div><p className="smart-alerts__eyebrow">{t('smartAlerts.activity')}</p><h2 id="smart-alerts-feed-title">{t('smartAlerts.alerts')}</h2></div>{data&&!query.isError&&<span className="smart-alerts__total" aria-live="polite">{t('smartAlerts.total',{value:formatCount(total)})}</span>}</div>
   <div className="smart-alerts__filters" role="group" aria-label={t('smartAlerts.filter')}>{states.map(item=><button key={item} type="button" className={`smart-alerts__filter ${state===item?'is-active':''}`} aria-pressed={state===item} onClick={()=>{setState(item);setPage(1);action.reset();}}>{t(`smartAlerts.states.${item}`)}</button>)}</div>
   {(query.isError||action.isError)&&<div className="smart-alerts__notice is-error" role="alert"><span>{t('smartAlerts.error')}</span><Button variant="outline" size="sm" onClick={()=>{action.reset();query.refetch();}}>{t('smartAlerts.refresh')}</Button></div>}
   {query.isPending&&<div className="smart-alerts__loading" role="status"><span className="smart-alerts__loading-icon" aria-hidden="true"/><span>{t('smartAlerts.loading')}</span></div>}
   {data&&!query.isError&&!events.length&&<EmptyState className="smart-alerts__empty" icon={<BellRing size={25}/>} title={t('smartAlerts.emptyTitle')} description={t('smartAlerts.empty')}/>}
   {events.length>0&&<div className="smart-alerts__list">{events.map(event=><AlertEvent key={event.alert_event_id} event={event} canManage={data.can_manage} action={action} t={t} locale={locale}/>)}</div>}
   {data&&!query.isError&&(total>20||page>1)&&<nav className="smart-alerts__pagination" aria-label={t('smartAlerts.pagination')}><span>{t('smartAlerts.showing',{start:formatCount((page-1)*20+1),end:formatCount(Math.min(page*20,total)),total:formatCount(total)})}</span><div><Button size="sm" variant="outline" disabled={page<=1||query.isFetching} onClick={()=>setPage(value=>value-1)}>{t('smartAlerts.previous')}</Button><Button size="sm" variant="outline" disabled={query.isFetching||page*20>=total} onClick={()=>setPage(value=>value+1)}>{t('smartAlerts.next')}</Button></div></nav>}
  </section>
  <section className="smart-alerts__rules dashboard-panel" aria-labelledby="smart-alerts-rules-title"><div className="smart-alerts__section-heading"><div><p className="smart-alerts__eyebrow">{t('smartAlerts.management')}</p><h2 id="smart-alerts-rules-title">{t('smartAlerts.rules')}</h2></div><span className="smart-alerts__total">{formatCount(rules.length)}</span></div>
   {query.isPending&&<p role="status">{t('smartAlerts.loading')}</p>}
   {data&&!rules.length&&<p className="smart-alerts__muted">{t('smartAlerts.noRules')}</p>}
   {rules.length>0&&<div className="smart-alerts__rule-list">{rules.map(rule=><article className="smart-alerts__rule" key={rule.alert_rule_id}><div className="smart-alerts__rule-copy"><div className="smart-alerts__rule-heading"><h3>{rule.name}</h3><span className={`smart-alerts__status ${rule.is_active?'is-acknowledged':'is-resolved'}`}><span aria-hidden="true"/>{t(rule.is_active?'smartAlerts.active':'smartAlerts.paused')}</span></div><p>{data.competitors.find(c=>c.id===rule.global_competitor_id)?.name??t('smartAlerts.competitor')} · {rule.metric==='PRICE_CHANGE_PERCENT'?`${t(`smartAlerts.operators.${rule.operator}`)} ${new Intl.NumberFormat(locale,{maximumFractionDigits:4}).format(Number(rule.threshold))}%`:t('smartAlerts.unsupported')}</p></div>{data.can_manage&&rule.metric==='PRICE_CHANGE_PERCENT'&&<Button variant="outline" size="sm" onClick={()=>{setEdit(rule.alert_rule_id);setForm({name:rule.name,global_competitor_id:rule.global_competitor_id,operator:rule.operator,threshold:Number(rule.threshold),cooldown_minutes:rule.cooldown_minutes,is_active:rule.is_active});save.reset();}}>{t('smartAlerts.edit')}</Button>}</article>)}</div>}
  </section>
  {data?.can_manage&&<section className="smart-alerts__editor dashboard-panel" id="smart-alerts-rule-form" aria-labelledby="smart-alerts-editor-title"><div className="smart-alerts__section-heading"><div><p className="smart-alerts__eyebrow"><SlidersHorizontal size={14} aria-hidden="true"/>{t('smartAlerts.configuration')}</p><h2 id="smart-alerts-editor-title">{t(edit?'smartAlerts.edit':'smartAlerts.create')}</h2></div></div>
   <p className="smart-alerts__muted">{t('smartAlerts.formHint')}</p>
   {save.isError&&<p className="smart-alerts__notice is-error" role="alert">{t('smartAlerts.error')}</p>}
   <form onSubmit={event=>{event.preventDefault();save.mutate();}}><div className="smart-alerts__fields">
    <label className="smart-alerts__field">{t('smartAlerts.name')}<input id="smart-alerts-rule-name" required maxLength={120} value={form.name} onChange={event=>setForm({...form,name:event.target.value})}/></label>
    <label className="smart-alerts__field">{t('smartAlerts.competitor')}<select required value={form.global_competitor_id} onChange={event=>setForm({...form,global_competitor_id:event.target.value})}><option value="">{t('smartAlerts.choose')}</option>{data.competitors.map(competitor=><option key={competitor.id} value={competitor.id}>{competitor.name}</option>)}</select></label>
    <label className="smart-alerts__field">{t('smartAlerts.operator')}<select value={form.operator} onChange={event=>setForm({...form,operator:event.target.value})}>{['GT','GTE','LT','LTE'].map(operator=><option key={operator} value={operator}>{t(`smartAlerts.operators.${operator}`)}</option>)}</select></label>
    <label className="smart-alerts__field">{t('smartAlerts.threshold')}<input required type="number" min={-100} max={10000} step="0.0001" value={form.threshold} onChange={event=>setForm({...form,threshold:Number(event.target.value)})}/></label>
    <label className="smart-alerts__field">{t('smartAlerts.cooldown')}<input required type="number" min={0} max={10080} step={1} value={form.cooldown_minutes} onChange={event=>setForm({...form,cooldown_minutes:Number(event.target.value)})}/></label>
   </div><label className="smart-alerts__checkbox"><input type="checkbox" checked={form.is_active} onChange={event=>setForm({...form,is_active:event.target.checked})}/>{t('smartAlerts.active')}</label>
   {!data.competitors.length&&<p className="smart-alerts__notice" role="status">{t('smartAlerts.noCompetitors')}</p>}
   <div className="smart-alerts__form-actions"><Button type="submit" disabled={save.isPending||!data.competitors.length} loading={save.isPending}>{t('smartAlerts.save')}</Button>{edit&&<Button variant="outline" onClick={resetForm}>{t('smartAlerts.cancel')}</Button>}</div>
   </form>
  </section>}
  <details className="smart-alerts__policy"><summary>{t('smartAlerts.policyTitle')}</summary><p>{t('smartAlerts.policy')}</p></details>
 </main>;
}

export function SmartAlertsPage(){ return COMPETITOR_AI_ACTIONS_ENABLED ? <ConnectedSmartAlertsPage/> : null; }

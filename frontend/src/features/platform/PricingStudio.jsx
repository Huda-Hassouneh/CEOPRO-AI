import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../auth/store/authStore.js';
import Button from '../../shared/components/ui/Button.jsx';
import Input from '../../shared/components/ui/Input.jsx';
import Card from '../../shared/components/ui/Card.jsx';
import Table from '../../shared/components/ui/Table.jsx';
import Skeleton from '../../shared/components/ui/Skeleton.jsx';
import EmptyState from '../../shared/components/ui/EmptyState.jsx';
import { platformBillingApi } from './platformBillingApi.js';
import { ASSUMPTION_FIELDS, COVERAGE, newPolicy, policyPayload, analysisPayload } from './pricingStudio.js';
import './pricingStudio.css';

const problem = e => e?.response?.data?.detail;

function PolicyEditor({ data, api, saved, cancel, text }) {
  const [form, setForm] = useState(() => newPolicy(data.selected_policy));
  const [error, setError] = useState('');
  const codes = [...new Set([...data.features.map(f=>f.feature_code),...data.entitlement_catalog])];
  const set = (key,value) => setForm(current => ({...current,[key]:value}));
  const mutation = useMutation({ mutationFn: body => api.createAnalysisPolicy(body), onSuccess: saved,
    onError: e => setError(typeof problem(e) === 'string' ? problem(e) : text('policyInvalid')) });
  const submit = event => {
    event.preventDefault(); setError('');
    try { mutation.mutate(policyPayload(form)); } catch { setError(text('policyInvalid')); }
  };
  return <form className="pricing-studio-policy" onSubmit={submit}>
    <h3>{text('newPolicy')}</h3><p>{text('explicitPolicy')}</p>
    {error && <p role="alert">{error}</p>}
    <div className="pricing-studio-fields">{ASSUMPTION_FIELDS.map(key => <Input key={key} label={text('fields.'+key)}
      value={form[key]} required={key !== 'ladder_min_price_gap'} onChange={event => set(key,event.target.value)} />)}
      <Input label={text('effectiveFrom')} value={form.effective_from} required onChange={event => set('effective_from',event.target.value)} />
      <Input label={text('reason')} value={form.reason} required onChange={event => set('reason',event.target.value)} />
      <label>{text('bindingPolicy')}<select value={form.cost_binding_policy_id} onChange={event => set('cost_binding_policy_id',event.target.value)}>
        <option value="">{text('notConfigured')}</option>{data.binding_policies.map(p => <option key={p.policy_version_id} value={p.policy_version_id}>{p.version_number} · {p.status}</option>)}
      </select></label>
      <label>{text('refresh')}<select value={form.refresh_frequency} onChange={event => set('refresh_frequency',event.target.value)}>
        <option value="">{text('notConfigured')}</option>{['hourly','every_6_hours','every_12_hours','daily','weekly'].map(c => <option key={c} value={c}>{text('cadences.'+c)}</option>)}
      </select></label>
    </div>
    <h4>{text('coverage')}</h4><p>{text('coverageHelp')}</p>
    <div className="pricing-studio-fields">{codes.filter(code => !['ai_credits','data_credits'].includes(code)).map(code => <label key={code}>{code}<select
      value={form.feature_treatments[code] || ''} onChange={event => set('feature_treatments',{...form.feature_treatments,[code]:event.target.value})}>
      <option value="">{text('notConfigured')}</option>{COVERAGE.map(c => <option key={c} value={c}>{text('treatments.'+c)}</option>)}
    </select></label>)}</div>
    <label>{text('unlimitedUsage')}<textarea rows={4} value={form.unlimited_monthly_usage} onChange={event => set('unlimited_monthly_usage',event.target.value)}/></label>
    <div className="pricing-studio-actions"><Button type="submit" loading={mutation.isPending}>{text('savePolicy')}</Button><Button variant="outline" disabled={mutation.isPending} onClick={cancel}>{text('cancel')}</Button></div>
  </form>;
}

export function PricingStudio({ api = platformBillingApi }) {
  const { t, locale, dir } = useI18n();
  const text = key => t('billing.pricingStudio.'+key);
  const [params, setParams] = useSearchParams();
  const actor = useAuthStore(state => state.user?.id || state.user?.user_id);
  const qc = useQueryClient();
  const key = ['platform',actor,'pricing-studio'];
  const query = useQuery({ queryKey:key,queryFn:api.pricingStudio,retry:false });
  const [mode, setMode] = useState('analyze');
  const [limits, setLimits] = useState({});
  const [entitlements, setEntitlements] = useState(null);
  const [refresh, setRefresh] = useState('');
  const [policyId, setPolicyId] = useState('');
  const [editor, setEditor] = useState(false);
  const analysis = useMutation({mutationFn:api.analyzePlan});
  const data = query.data;
  const plan = data?.plans.find(p => p.plan_key === params.get('plan')) || data?.plans[0];
  const result = analysis.data;
  const money = (value,currency='JOD') => value == null ? '—' : new Intl.NumberFormat(locale,{style:'currency',currency}).format(Number(value));
  const percent = value => value == null ? '—' : new Intl.NumberFormat(locale,{style:'percent',maximumFractionDigits:2}).format(Number(value));
  const changePlan = value => { const next = new URLSearchParams(params); next.set('plan',value); setParams(next); setLimits({}); setEntitlements(null); setRefresh(''); analysis.reset(); };
  const run = () => analysis.mutate(analysisPayload(plan.plan_key,mode,limits,entitlements ?? plan.entitlements,refresh,policyId));
  if (query.isPending) return <Skeleton height="240px" />;
  if (query.isError) return <EmptyState title={text('loadError')} description={typeof problem(query.error)==='string'?problem(query.error):text('ownerOnly')} />;
  if (!plan) return <EmptyState title={text('noPlans')} />;
  return <section className="pricing-studio" dir={dir}>
    <header><h2>{text('title')}</h2><p>{text('subtitle')}</p></header>
    <p className="pricing-studio-boundary" role="note">{text('analysisOnly')}</p>
    <div className="pricing-studio-toolbar">
      <label>{text('plan')}<select aria-label={text('plan')} value={plan.plan_key} onChange={event => changePlan(event.target.value)}>{data.plans.map(p => <option key={p.plan_key} value={p.plan_key}>{locale==='ar'?p.display_name_ar||p.display_name:p.display_name}</option>)}</select></label>
      <label>{text('mode')}<select aria-label={text('mode')} value={mode} onChange={event => {setMode(event.target.value);analysis.reset();}}><option value="analyze">{text('analyze')}</option><option value="simulate">{text('simulate')}</option></select></label>
      <label>{text('policy')}<select aria-label={text('policy')} value={policyId} onChange={event => {setPolicyId(event.target.value);analysis.reset();}}><option value="">{text('effectivePolicy')}</option>{data.policies.map(p => <option key={p.policy_id} value={p.policy_id}>{p.version} · {new Date(p.effective_from).toLocaleString(locale)}</option>)}</select></label>
      <Button onClick={run} loading={analysis.isPending}>{text('run')}</Button>
      <Button variant="outline" onClick={() => setEditor(!editor)}>{text('newPolicy')}</Button>
    </div>
    {editor && <PolicyEditor data={data} api={api} text={text} cancel={()=>setEditor(false)} saved={async()=>{setEditor(false);analysis.reset();await qc.invalidateQueries({queryKey:key});}} />}
    <details className="pricing-studio-contract"><summary>{text('actualConfiguration')}</summary>
      <ul>{plan.feature_limits.map(f => <li key={f.feature_code}>{f.feature_code}: {f.limit_value??text('unbounded')} {f.unit} · {f.reset_cycle} · {f.aggregation_type}</li>)}</ul>
      <p>{text('included')}: {plan.entitlements.join(', ')}</p>
      <p>{text('cadenceContract')}</p>
    </details>
    {mode==='simulate' && <Card className="pricing-studio-simulation"><h3>{text('simulate')}</h3><p>{text('simulationNote')}</p>
      <div className="pricing-studio-fields">{plan.feature_limits.map(f => <Input key={f.feature_code} label={f.feature_code} type="number" min="0" step="1"
        value={Object.hasOwn(limits,f.feature_code)?limits[f.feature_code]:f.limit_value??''} onChange={event=>{setLimits({...limits,[f.feature_code]:event.target.value});analysis.reset();}} />)}
        <label>{text('refresh')}<select value={refresh} onChange={event=>{setRefresh(event.target.value);analysis.reset();}}><option value="">{text('policyAssumption')}</option>{['hourly','every_6_hours','every_12_hours','daily','weekly'].map(c=><option key={c} value={c}>{text('cadences.'+c)}</option>)}</select></label>
      </div><div className="pricing-studio-modules">{data.entitlement_catalog.map(code=><label key={code}><input type="checkbox" checked={(entitlements??plan.entitlements).includes(code)} onChange={event=>{const old=entitlements??plan.entitlements;setEntitlements(event.target.checked?[...old,code]:old.filter(c=>c!==code));analysis.reset();}} />{code}</label>)}</div>
    </Card>}
    {analysis.error && <p role="alert">{typeof problem(analysis.error)==='string'?problem(analysis.error):text('analysisError')}</p>}
    {result && <>
      <div className="pricing-studio-result-heading"><h3>{text('result')}</h3><strong className={'pricing-studio-status status-'+result.status}>{text('statuses.'+result.status)}</strong><span>{text('policy')}: {result.policyVersion??'—'}</span></div>
      {result.warnings.length>0 && <ul role="alert" className="pricing-studio-warnings">{result.warnings.map((w,i)=><li key={i}>{text('warnings.'+w.split(':')[0])}{w.includes(':')?' · '+w.split(':').slice(1).join(':'):''}</li>)}</ul>}
      <div className="pricing-studio-summary">{['expected','stress'].map(s=><Card key={s}><span>{text('cost.'+s)}</span><strong data-testid={'cost-'+s}>{money(result.costs?.[s])}</strong><small>{result.costs?.knownSubtotalOnly?text('subtotalOnly'):text('configuredModel')}</small></Card>)}
        {['breakEven','safeMinimum','recommended','currentJod'].map(s=><Card key={s}><span>{text('pricing.'+s)}</span><strong data-testid={'price-'+s}>{money(result.pricing?.[s])}</strong></Card>)}
      </div>
      {result.pricing && <Card><h3>{text('commercialComparison')}</h3><div className="pricing-studio-metrics"><span>{text('published')}: <strong>{money(result.pricing.publishedAmount,result.pricing.publishedCurrency)}</strong></span><span>{text('difference')}: {money(result.pricing.difference)}</span><span>{text('contribution')}: {money(result.pricing.contribution)}</span><span>{text('expectedMargin')}: {percent(result.pricing.expectedMargin)}</span><span>{text('stressMargin')}: {percent(result.pricing.stressMargin)}</span></div></Card>}
      {result.costs && <Card><h3>{text('breakdown')}</h3><p>{text('exposureNote')}</p><Table data={[...result.costs.breakdown].sort((a,b)=>Number(b.stress)-Number(a.stress))} columns={[
        {header:text('feature'),accessor:'feature'},{header:text('classification'),render:r=>text('classifications.'+r.classification)},
        {header:text('cost.expected'),render:r=>money(r.expected)},{header:text('cost.stress'),render:r=>money(r.stress)},
      ]}/><p>{text('internal')}: {money(result.costs.internal)}</p></Card>}
      {result.periods && <Card><h3>{text('periodEconomics')}</h3><p>{text('periodNote')}</p><Table data={result.periods} columns={[
        {header:text('period'),accessor:'period'},{header:text('revenue'),render:r=>money(r.revenueJod)},
        {header:text('cost.expected'),render:r=>money(r.expectedCost)},{header:text('cost.stress'),render:r=>money(r.stressCost)},
        {header:text('expectedMargin'),render:r=>percent(r.expectedMargin)},{header:text('stressMargin'),render:r=>percent(r.stressMargin)},
      ]}/></Card>}
      {result.annual && <Card><h3>{text('annual')}</h3><p>{text('annualNote')}</p><div className="pricing-studio-metrics"><span>{text('candidate')}: {money(result.annual.discountedCandidate)}</span><span>{text('pricing.safeMinimum')}: {money(result.annual.safeMinimum)}</span><span>{text('cost.expected')}: {money(result.annual.expectedCost)}</span><span>{text('cost.stress')}: {money(result.annual.stressCost)}</span><span>{text('expectedMargin')}: {percent(result.annual.expectedMargin)}</span><span>{text('annualCycles')}: {result.annual.allowanceCycles}</span></div></Card>}
      <Card><h3>{text('neighbors')}</h3><Table data={result.neighbors} columns={[
        {header:text('plan'),accessor:'planKey'},{header:text('cost.stress'),render:r=>money(r.costs?.stress)},
        {header:text('pricing.currentJod'),render:r=>money(r.pricing?.currentJod)},{header:text('pricing.recommended'),render:r=>money(r.pricing?.recommended)},
      ]}/>{result.ladderWarnings.map((w,i)=><p key={i}>{text('warnings.'+w.code)} · {w.lower} → {w.higher}</p>)}</Card>
      <details className="pricing-studio-evidence"><summary>{text('evidence')}</summary><p>{text('evidenceNote')}</p>
        <p>{text('snapshot')}: {result.analysisId}<br/>{text('hash')}: {result.sourceHash}<br/>{text('asOf')}: {new Date(result.asOf).toLocaleString(locale)}</p>
        {result.fx && <p>USD → JOD: {result.fx.usdToJod} · {result.fx.source} · {result.fx.version}</p>}
        <h4>{text('assumptions')}</h4><pre>{JSON.stringify(result.assumptions,null,2)}</pre>
        <h4>{text('rateEvidence')}</h4><pre>{JSON.stringify(result.rateEvidence||[],null,2)}</pre>
        <h4>{text('observedSpend')}</h4><p>{text('observedNote')}</p><p>{result.evidence.window.from} → {result.evidence.window.to}</p><Table data={result.observations} columns={[
          {header:text('budgetKind'),accessor:'budget_kind'},{header:text('settledSpend'),render:r=>money(r.settled_cost_usd,'USD')},
          {header:text('pendingSpend'),render:r=>money(r.pending_estimate_usd,'USD')},{header:text('entries'),accessor:'entries'},
        ]}/>
        <h4>{text('providerCatalog')}</h4><Table data={result.evidence.providerSchedules} columns={[
          {header:text('provider'),render:r=>r.provider+' / '+r.operation+' / '+r.unit},
          {header:text('providerUsd'),render:r=>r.unit_cost_usd??text('notConfigured')},
          {header:text('verification'),render:r=>text('rateStatuses.'+r.analysisStatus)},
          {header:text('source'),accessor:'source'},{header:text('verifiedAt'),accessor:'verified_at'},
        ]}/>
      </details>
    </>}
  </section>;
}

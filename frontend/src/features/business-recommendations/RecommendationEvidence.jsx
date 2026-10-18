export function RecommendationEvidence({evidence={},t,locale='en'}){
 const format=value=>value?new Intl.DateTimeFormat(locale,{dateStyle:'medium',timeStyle:'short'}).format(new Date(value)):'—';
 const number=value=>value==null?'—':new Intl.NumberFormat(locale,{maximumFractionDigits:2}).format(value);
 return <details><summary>{t('businessRecommendations.evidence')}</summary>
  {evidence.generated_at&&<p>{t('businessRecommendations.asOf',{date:format(evidence.generated_at)})}</p>}
  {evidence.sales&&<p>{t('businessRecommendations.salesEvidence',{source:t('businessRecommendations.salesSources.'+evidence.sales.source),
    recent:number(evidence.sales.recent_units),prior:number(evidence.sales.prior_units),count:number(evidence.sales.record_count)})}</p>}
  {evidence.feedback?.record_count>0&&<p>{t('businessRecommendations.feedbackEvidence',{count:evidence.feedback.record_count,scope:t('businessRecommendations.feedbackScopes.'+evidence.feedback.scope)})}</p>}
  <ul>{(evidence.sources??[]).map((s,index)=><li key={s.record_id??index}>
   {s.table==='competitor_prices'?<>{s.competitor_name}{' · '}{number(s.price)} {s.currency}{' · '}{format(s.observed_at)}</>:
    s.table==='demand_forecasts'?t('businessRecommendations.dailyForecast',{units:number(s.expected_units),date:s.target_date}):null}
  </li>)}</ul>
  {evidence.detector_facts?.forecast_kind==='complete_30_target_days'&&<p>{t('businessRecommendations.fullForecast',{units:number(evidence.detector_facts.forecast_total),stock:number(evidence.detector_facts.stock_units)})}</p>}
  {evidence.detector_facts?.category&&<p>{t('businessRecommendations.categoryEvidence',{category:evidence.detector_facts.category,count:evidence.detector_facts.competitor_count})}</p>}
  {evidence.detector_facts?.event_date&&<p>{t('businessRecommendations.timingEvidence',{date:evidence.detector_facts.event_date,price:number(evidence.detector_facts.price_drop_pct),sales:number(evidence.detector_facts.sales_change_pct)})}</p>}
  <p>{t('businessRecommendations.caution')}</p>
 </details>;
}

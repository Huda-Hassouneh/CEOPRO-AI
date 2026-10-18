function ObservationList({ sources, t, formatDate, money }) {
  return <ul className="pricing-recommendation__sources">{sources.map(source => (
    <li key={source.competitor_price_id}>
      <div><strong>{source.competitor_name}</strong>
        <span><bdi>{money(source.original_price, source.original_currency)}</bdi>
          {source.conversion && <> → <bdi>{money(source.converted_price, source.currency)}</bdi></>}</span>
      </div>
      <small>{formatDate(source.observed_at)}
        {source.conversion && <> · {t("marketMain.pricingFix.fxRate", {
          rate: source.conversion.rate, date: formatDate(source.conversion.as_of), source: source.conversion.source
        })}</>}
      </small>
    </li>
  ))}</ul>;
}

export function PricingEvidenceDetails({ recommendation, showSummary = true, t, localize, formatDate, money }) {
  if (!recommendation) return null;
  return <>
    {showSummary && <>
      <p>{t("marketMain.pricingFix.generatedAt", { date: formatDate(recommendation.generated_at) })}</p>
      {recommendation.is_stale && <p role="status">{t("marketMain.pricingFix.stale")}</p>}
      {recommendation.status === "UNKNOWN" && <p role="status">{localize(recommendation.explanation_i18n) ?? recommendation.explanation}</p>}
      {recommendation.status === "OK" && Number.isFinite(recommendation.confidence_score) &&
        <p>{t("marketMain.pricingFix.confidence", { count: Math.round(recommendation.confidence_score * 100) })}</p>}
    </>}
    {recommendation.sources?.length > 0 && <details className="pricing-recommendation__details">
      <summary>{t("marketMain.pricingFix.sources", { count: recommendation.sources.length })}</summary>
      {recommendation.market_freshness_days != null && recommendation.fx_freshness_days != null &&
        <p>{t("marketMain.pricingFix.sourceWindow", {
          days: recommendation.market_freshness_days, fxDays: recommendation.fx_freshness_days
        })}</p>}
      <ObservationList sources={recommendation.sources} t={t} formatDate={formatDate} money={money} />
    </details>}
    {recommendation.reference_sources?.length > 0 && <details className="pricing-recommendation__details">
      <summary>{t("marketMain.pricingFix.referenceSources")}</summary>
      <p>{t("marketMain.pricingFix.referenceOnly")}</p>
      <ObservationList sources={recommendation.reference_sources} t={t} formatDate={formatDate} money={money} />
    </details>}
  </>;
}

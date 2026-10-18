import Button from "../../../shared/components/ui/Button.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { UI_TESTING_MODE } from "../../../shared/config/uiTestingMode.js";
import { useForecastGeneration } from "../hooks/useForecastGeneration.js";
import { ForecastCoverage } from "./ForecastCoverage.jsx";
import { forecastFormatters } from "../utils/forecastFormatters.js";

export function ForecastGenerationPanel({ productId, periodDays, coverage, latestPrediction, generatedAt, locale, t, refreshBlocked = false }) {
  const generation = useForecastGeneration(productId, periodDays);
  const f = forecastFormatters(locale);
  const result = generation.data;
  const point = result?.status === "OK" ? {
    date: result.forecast_target_date, forecastedDemand: result.expected_demand,
    source: result.source, generatedAt: result.generated_at ?? result.checked_at, confidenceScore: result.confidence_score,
    modelVersion: result.model_version
  } : latestPrediction;
  const canGenerate = Boolean(productId && productId !== "all");
  return <section className="forecast-generation" aria-busy={generation.isPending || undefined}>
    <div className="forecast-generation__header">
      <div><h2>{t("demandApproved.generation.title")}</h2><p>{t("demandApproved.generation.description")}</p></div>
      <Button size="sm" onClick={generation.generate} disabled={!canGenerate || UI_TESTING_MODE || refreshBlocked}
        loading={generation.isPending} loadingLabel={t("demandApproved.generation.loading")}>
        {t(point ? "demandApproved.generation.refresh" : "demandApproved.generation.generate")}
      </Button>
    </div>
    {!canGenerate && <p>{t("demandApproved.generation.selectProduct")}</p>}
    {canGenerate && <div className="forecast-generation__meta">
      <ForecastCoverage coverage={coverage} periodDays={periodDays} t={t} />
      <span>{t("demandApproved.generation.lastGenerated", { date: f.formatDate(point?.generatedAt ?? generatedAt) })}</span>
    </div>}
    {generation.isPending && <p role="status">{t("demandApproved.generation.progress")}</p>}
    {generation.error && <p className="forecast-generation__error" role="alert">{getApiErrorMessage(generation.error, t)}</p>}
    {result?.status === "UNKNOWN" && <p role="status">{t(`demandApproved.generation.reasons.${result.reason}`)}</p>}
    {point && <div className="forecast-generation__result">
      <strong>{t(point.predictionKind === "period_total" ? "demandApproved.generation.periodResult" : "demandApproved.generation.targetResult", {
        value: f.formatNumber(point.forecastedDemand), date: f.formatDate(point.date)
      })}</strong>
      {typeof point.source === "string" && ["baseline", "xgboost"].includes(point.source) && <span>{t(`demandApproved.generation.sources.${point.source}`)}</span>}
      {typeof point.confidenceScore === "number" && point.confidenceScore >= 0 && point.confidenceScore <= 1 &&
        <span>{t("demandApproved.generation.confidence", { value: f.formatNumber(point.confidenceScore * 100) })}</span>}
      {point.modelVersion && <span>{t("demandApproved.generation.modelVersion", { version: point.modelVersion })}</span>}
      {point.predictionKind !== "period_total" && <p>{t("demandApproved.generation.targetNote")}</p>}
    </div>}
    {result?.latest_history_date && <small>{t("demandApproved.generation.historyThrough", { date: f.formatDate(result.latest_history_date) })}</small>}
  </section>;
}

import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { perceptionPresentation } from "../utils/marketPerceptionPresentation.js";

export function MarketPerceptionResult({ summary, fallbackStatus = "NOT_ANALYZED", compact = false }) {
  const { t, locale } = useI18n();
  const result = perceptionPresentation(summary, fallbackStatus);
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const percent = new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 });
  const date = (value) => {
    const parsed = value ? new Date(value) : null;
    return parsed && Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat(locale, {
      year: "numeric", month: "short", day: "numeric", timeZone: "UTC"
    }).format(parsed) : "—";
  };
  const evidence = result.evidence;
  return (
    <div className={`market-perception-result ${compact ? "is-compact" : ""}`}>
      {result.supported ? <>
        <strong className="market-perception-score">{number.format(result.score)} / 100</strong>
        <span className={`market-main-badge is-${result.dominantLabel ?? "neutral"}`}>
          {result.dominantLabel ? t(`marketMain.sentiments.${result.dominantLabel}`) : t("marketPerception.mixedFeedback")}
        </span>
      </> : <span className="market-perception-state" role="status">{t(`marketPerception.states.${result.status}`)}</span>}
      {result.reviewCount !== null && <small className="market-main-source-date">
        {t("marketPerception.reviewCount", { count: number.format(result.reviewCount) })}
        {result.status === "INSUFFICIENT_REVIEWS" && result.minimum !== null ? ` · ${t("marketPerception.minimum", { count: number.format(result.minimum) })}` : ""}
      </small>}
      {evidence && <details className="market-perception-evidence">
        <summary>{t("marketPerception.evidence")}</summary>
        {summary?.analysis_performed && evidence.eligible_review_count !== result.reviewCount && <p>
          {t("marketPerception.eligibleReviewCount", { count: number.format(evidence.eligible_review_count ?? 0) })}
        </p>}
        {result.labels && <p>{["positive", "neutral", "negative"].map((label) =>
          `${t(`marketMain.sentiments.${label}`)}: ${number.format(result.labels[label] ?? 0)}`).join(" · ")}</p>}
        <p>{t("marketPerception.period", { start: date(evidence.observation_period?.start), end: date(evidence.observation_period?.end) })}</p>
        <p>{t("marketPerception.sampleBasis", { count: number.format(evidence.sample_limit ?? 100) })}</p>
        {result.confidence !== null && <p>{t("marketPerception.confidence", { value: percent.format(result.confidence) })}<br />{t("marketPerception.confidenceHint")}</p>}
        {evidence.collection_methods?.length > 0 && <p>{t("marketPerception.sources", { sources: evidence.collection_methods.map((method) => t(`marketPerception.methods.${method}`)).join(" · ") })}</p>}
        {result.asOf && <p>{t("marketPerception.checkedAt", { date: date(result.asOf) })}</p>}
        {evidence.explanation && <p dir="auto">{evidence.explanation}</p>}
      </details>}
    </div>
  );
}

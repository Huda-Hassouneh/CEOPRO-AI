import { useId } from "react";
import { CircleAlert, Clock3, Info, Sparkles } from "lucide-react";
import Button from "../../../shared/components/ui/Button.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { PricingEvidenceDetails } from "./PricingEvidenceDetails.jsx";

/** Presentation only: requests, history selection, entitlement and export stay in the page. */
export function PricingRecommendationContent({
  recommendation, row, productName, savedRecommendations, credits,
  historyLoading, historyError, isGenerating, errorMessage,
  onSelect, onReloadHistory, onDismissError, t, localize, formatDate, money, number
}) {
  const historyId = useId();
  const result = recommendation?.status === "OK";
  const explanation = localize(recommendation?.explanation_i18n)
    || recommendation?.explanation || null;
  const action = result && ["raise", "lower", "hold"].includes(row?.action) ? row.action : null;
  const stats = [
    ["marketAverage", row?.marketAverage],
    ["marketMedian", row?.marketMedian],
    ["marketMin", row?.marketMin],
    ["marketMax", row?.marketMax]
  ];
  const hasStats = stats.some(([, value]) => value != null) || row?.matchedCompetitors != null;

  return (
    <div className="pricing-recommendation">
      <div className="pricing-recommendation__toolbar">
        <p className="pricing-recommendation__credits">
          {credits.isUnlimited ? t("marketMain.pricingFix.unlimitedCredits")
            : t("marketMain.pricingFix.remainingCredits", { count: number(credits.remaining ?? 0) })}
        </p>
        {savedRecommendations.length > 1 && (
          <label className="pricing-recommendation__history" htmlFor={historyId}>
            <span>{t("marketMain.pricingFix.savedRecommendations")}</span>
            <select id={historyId} className="market-main-select"
              value={recommendation?.request_id ?? ""} disabled={isGenerating}
              onChange={event => onSelect(event.target.value)}>
              {savedRecommendations.map(item => (
                <option key={item.request_id} value={item.request_id}>
                  {formatDate(item.generated_at)} · {item.status === "OK"
                    ? money(item.suggested_price, item.currency)
                    : t("marketMain.pricingUx.unavailableLabel")}
                  {item.is_stale ? ` · ${t("marketMain.pricingUx.historical")}` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {historyError && (
        <div className="pricing-recommendation__notice" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <p>{t("marketMain.pricingFix.historyError")}</p>
          <Button size="sm" variant="outline" onClick={onReloadHistory} disabled={historyLoading}>
            {t("marketMain.actions.retry")}
          </Button>
        </div>
      )}
      {errorMessage && (
        <div className="pricing-recommendation__notice is-error" role="alert">
          <CircleAlert size={18} aria-hidden="true" />
          <div><strong>{t("marketMain.pricingUx.errorTitle")}</strong><p>{errorMessage}</p></div>
          <Button size="sm" variant="ghost" onClick={onDismissError}>
            {t("marketMain.pricingUx.dismiss")}
          </Button>
        </div>
      )}

      {isGenerating && <p className="pricing-recommendation__progress" role="status">
        {t("marketMain.pricingUx.generatingDescription")}
      </p>}
      {historyLoading && !isGenerating && <p className="pricing-recommendation__progress" role="status">
        {t("marketMain.pricingFix.loadingHistory")}
      </p>}

      {recommendation ? (
        <>
          <div className="pricing-recommendation__identity">
            <h3>{productName}</h3>
            <p><Clock3 size={14} aria-hidden="true" />
              {t("marketMain.pricingFix.generatedAt", { date: formatDate(recommendation.generated_at) })}
            </p>
          </div>
          {recommendation.is_stale && (
            <div className="pricing-recommendation__notice" role="status">
              <Clock3 size={18} aria-hidden="true" /><p>{t("marketMain.pricingFix.stale")}</p>
            </div>
          )}
          {result ? (
            <div className="pricing-recommendation__result">
              <div className="pricing-recommendation__prices">
                <dl className="pricing-recommendation__price">
                  <dt>{t(recommendation.is_stale ? "marketMain.pricingUx.recordedPrice" : "marketMain.tables.currentPrice")}</dt>
                  <dd><bdi>{money(row?.currentPrice, row?.currency)}</bdi></dd>
                </dl>
                <dl className="pricing-recommendation__price is-suggested">
                  <dt>{t("marketMain.tables.suggestedPrice")}</dt>
                  <dd><bdi>{money(row?.suggestedPrice, row?.currency)}</bdi></dd>
                  {action && <span className="pricing-recommendation__action">
                    {t(`marketMain.pricingUx.actions.${action}`)}
                  </span>}
                </dl>
              </div>
              <div className="pricing-recommendation__reason">
                <h4>{t("marketMain.pricingUx.why")}</h4>
                <p>{explanation || t("marketMain.pricingUx.explanationMissing")}</p>
                {Number.isFinite(recommendation.confidence_score) && (
                  <small>{t("marketMain.pricingFix.confidence", {
                    count: number(Math.round(recommendation.confidence_score * 100))
                  })}</small>
                )}
              </div>
            </div>
          ) : (
            <div className="pricing-recommendation__empty">
              <span className="pricing-recommendation__icon"><Info size={22} aria-hidden="true" /></span>
              <div>
                <h4>{t("marketMain.pricingUx.unavailableTitle")}</h4>
                <p>{explanation || t("marketMain.pricingUx.unavailableDescription")}</p>
                <p>{t("marketMain.pricingUx.nextStep")}</p>
              </div>
            </div>
          )}
        </>
      ) : historyLoading || isGenerating ? (
        <div className="pricing-recommendation__skeleton" aria-hidden="true">
          <Skeleton height="28px" width="55%" />
          <div><Skeleton height="110px" variant="rectangular" /><Skeleton height="110px" variant="rectangular" /></div>
        </div>
      ) : (
        <div className="pricing-recommendation__empty">
          <span className="pricing-recommendation__icon"><Sparkles size={22} aria-hidden="true" /></span>
          <div><h3>{productName}</h3><h4>{t("marketMain.pricingUx.emptyTitle")}</h4>
            <p>{t("marketMain.pricingUx.emptyDescription")}</p>
            {row?.currentPrice != null && <dl className="pricing-recommendation__starting-price">
              <dt>{t("marketMain.tables.currentPrice")}</dt>
              <dd><bdi>{money(row.currentPrice, row.currency)}</bdi></dd>
            </dl>}
          </div>
        </div>
      )}
      {hasStats && (
        <details className="pricing-recommendation__details">
          <summary>{t("marketMain.pricingUx.marketDetails")}</summary>
          <dl className="pricing-recommendation__stats">
            <div><dt>{t("marketMain.tables.matchedCompetitors")}</dt>
              <dd>{row?.matchedCompetitors == null ? "—" : number(row.matchedCompetitors)}</dd></div>
            {stats.filter(([, value]) => value != null).map(([key, value]) => <div key={key}>
              <dt>{t(`marketMain.tables.${key}`)}</dt><dd><bdi>{money(value, row?.currency)}</bdi></dd>
            </div>)}
          </dl>
        </details>
      )}
      <PricingEvidenceDetails recommendation={recommendation} showSummary={false}
        t={t} localize={localize} formatDate={formatDate} money={money} />
      <p className="pricing-recommendation__policy"><Info size={16} aria-hidden="true" />
        <span>{t("marketMain.pricingFix.chargePolicy")}</span>
      </p>
    </div>
  );
}

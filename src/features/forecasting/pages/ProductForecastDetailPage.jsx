import { useMemo } from "react";
import {
  ArrowLeft,
  BrainCircuit,
  CalendarDays,
  Gauge,
  Package,
  Sparkles,
  Target
} from "lucide-react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { routePaths } from "../../../app/router/routePaths.js";
import BusinessPageContainer from "../../../shared/components/layout/BusinessPageContainer.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import DataStatusBadge from "../../../shared/components/ui/DataStatusBadge.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { DemandDataSection } from "../components/DemandDataSection.jsx";
import { DemandForecastChart } from "../components/DemandForecastChart.jsx";
import { DemandForecastTable } from "../components/DemandForecastTable.jsx";
import { DemandStatusBadge } from "../components/DemandStatusBadge.jsx";
import { useDemandPdfExport } from "../hooks/useDemandPdfExport.js";
import { useForecastDetail } from "../hooks/useForecastDetail.js";
import {
  forecastFormatters,
  localize
} from "../utils/forecastFormatters.js";
import "../styles/DemandPrediction.css";

const metricIcons = {
  currentStock: Package,
  expectedDemand: Sparkles,
  targetDate: CalendarDays,
  confidenceRange: Target,
  modelAccuracy: Gauge
};

export function ProductForecastDetailPage() {
  const { t, locale, dir } = useI18n();
  const { productId } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const periodDays = params.get("periodDays") === "7" ? 7 : 30;
  const query = useForecastDetail(productId, periodDays);
  const detail = query.data;

  const {
    formatNumber,
    formatDate,
    formatRange,
    formatPeriod,
    formatMetric: formatMetricValue
  } = useMemo(() => forecastFormatters(locale), [locale]);

  const canExport = Boolean(
    detail &&
      !query.isFetching &&
      !query.isError &&
      !query.isPlaceholderData &&
      detail.product?.id === productId &&
      detail.filters?.periodDays === periodDays
  );

  const {
    exporting,
    exportError,
    clearExportError,
    requestExport
  } = useDemandPdfExport({
    data: detail,
    locale,
    scope: `${productId}:${periodDays}:detail`,
    enabled: canExport
  });

  if (query.isPending) {
    return (
      <div className="demand-approved-loading" aria-busy="true">
        <Skeleton height="74px" variant="rectangular" />
        <div>
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} height="118px" variant="rectangular" />
          ))}
        </div>
        <Skeleton height="330px" variant="rectangular" />
      </div>
    );
  }

  if (query.isError && query.error?.response?.status !== 404) {
    return (
      <EmptyState
        title={t("demandApproved.error.detailTitle")}
        description={query.error?.response?.status === 403 ? t("demandApproved.error.access") : getApiErrorMessage(query.error, t)}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("demandApproved.actions.retry")}
          </Button>
        }
      />
    );
  }

  if (!detail || query.error?.response?.status === 404) {
    return (
      <EmptyState
        title={t("demandApproved.empty.detailTitle")}
        description={t("demandApproved.empty.detailDescription")}
        action={
          <Button size="sm" onClick={() => navigate(routePaths.forecasts)}>
            {t("demandApproved.actions.back")}
          </Button>
        }
      />
    );
  }

  const formatMetric = (metric) =>
    formatMetricValue(metric, t("demandApproved.common.units"));

  const historyColumns = [
    {
      key: "date",
      label: t("demandApproved.history.date"),
      render: (row) => formatPeriod(row)
    },
    {
      key: "forecastedDemand",
      label: t("demandApproved.history.forecast"),
      render: (row) => formatNumber(row.forecastedDemand)
    },
    {
      key: "lowerBound",
      label: t("demandApproved.history.lower"),
      render: (row) => formatNumber(row.lowerBound)
    },
    {
      key: "upperBound",
      label: t("demandApproved.history.upper"),
      render: (row) => formatNumber(row.upperBound)
    },
    {
      key: "actualDemand",
      label: t("demandApproved.history.actual"),
      render: (row) =>
        row.actualDemand == null
          ? t("demandApproved.common.notAvailable")
          : formatNumber(row.actualDemand)
    }
  ];

  return (
    <BusinessPageContainer
      wide
      className="demand-approved-page demand-approved-detail"
      dir={dir}
    >
      <button
        type="button"
        className="demand-approved-back"
        onClick={() => navigate(routePaths.forecasts)}
      >
        <ArrowLeft size={15} />
        {t("demandApproved.actions.back")}
      </button>

      <header className="demand-approved-detail__title">
        <span>
          <Package size={24} />
        </span>
        <div>
          <h1>{localize(detail.product.name, locale)}</h1>
          <p>{localize(detail.product.category, locale)}</p>
        </div>
      </header>

      <section className="demand-approved-detail-metrics">
        {detail.metrics.map((metric) => {
          const Icon = metricIcons[metric.id] || Package;
          return (
            <Card key={metric.id} className="demand-approved-detail-metric">
              <div>
                <span>
                  <Icon size={17} />
                </span>
                <DataStatusBadge status={metric.dataStatus} />
              </div>
              <small>{t(`demandApproved.detailMetrics.${metric.id}`)}</small>
              <strong>{formatMetric(metric)}</strong>
            </Card>
          );
        })}
      </section>

      <DemandDataSection
        title={t("demandApproved.detail.chartTitle")}
        subtitle={t("demandApproved.detail.chartSubtitle")}
        dataStatus={detail.chart?.dataStatus}
        className="demand-approved-chart-panel"
      >
        <DemandForecastChart
          points={detail.chart?.points ?? []}
          detailed
          t={t}
          formatDate={formatDate}
          formatNumber={formatNumber}
        />
        <div className="demand-approved-chart-legend">
          <span className="is-actual">{t("demandApproved.chart.actual")}</span>
          <span className="is-forecast">
            {t("demandApproved.chart.forecast")}
          </span>
          <span className="is-confidence">
            {t("demandApproved.chart.confidence")}
          </span>
        </div>
      </DemandDataSection>

      <section className="demand-approved-detail-grid">
        <DemandDataSection
          title={t("demandApproved.history.title")}
          subtitle={t("demandApproved.history.subtitle")}
          dataStatus={detail.forecastHistory?.[0]?.dataStatus}
          exportLabel={t(
            exporting
              ? "demandApproved.export.loading"
              : "demandApproved.actions.exportPdf"
          )}
          exportDisabled={!canExport}
          exporting={exporting}
          onExport={requestExport}
        >
          <DemandForecastTable
            className="is-history"
            columns={historyColumns}
            rows={detail.forecastHistory ?? []}
            emptyState={
              <EmptyState
                title={t("demandApproved.empty.historyTitle")}
                description={t("demandApproved.empty.historyDescription")}
              />
            }
          />
        </DemandDataSection>

        <section className="demand-approved-recommendation">
          <div className="demand-approved-panel__header">
            <div>
              <h2>{t("demandApproved.recommendation.title")}</h2>
              <p>{t("demandApproved.recommendation.subtitle")}</p>
            </div>
            <DataStatusBadge status={detail.recommendation?.dataStatus} />
          </div>

          {detail.recommendation ? (
            <>
              <DemandStatusBadge
                value={detail.recommendation.action}
                namespace="demandApproved.recommendations"
                t={t}
              />
              <dl>
                <div>
                  <dt>{t("demandApproved.recommendation.quantity")}</dt>
                  <dd>
                    {formatNumber(detail.recommendation.suggestedQuantity)}
                  </dd>
                </div>
                <div>
                  <dt>{t("demandApproved.recommendation.priority")}</dt>
                  <dd>
                    {detail.recommendation.priority
                      ? t(
                          `demandApproved.priorities.${detail.recommendation.priority}`
                        )
                      : t("demandApproved.common.notAvailable")}
                  </dd>
                </div>
                <div>
                  <dt>{t("demandApproved.recommendation.targetDate")}</dt>
                  <dd>
                    {formatPeriod({
                      date: detail.recommendation.startDate,
                      endDate: detail.recommendation.targetDate
                    })}
                  </dd>
                </div>
                <div>
                  <dt>{t("demandApproved.recommendation.accuracy")}</dt>
                  <dd>
                    {detail.recommendation.modelAccuracy == null
                      ? t("demandApproved.common.notAvailable")
                      : `${formatNumber(
                          detail.recommendation.modelAccuracy
                        )}%`}
                  </dd>
                </div>
              </dl>
            </>
          ) : (
            <EmptyState
              title={t("demandApproved.empty.recommendationTitle")}
              description={t("demandApproved.empty.recommendationDescription")}
            />
          )}
        </section>
      </section>

      {detail.aiInsight && (
        <section className="demand-approved-product-insight">
          <div>
            <span>
              <BrainCircuit size={18} />
            </span>
            <div>
              <h2>{t("demandApproved.insight.title")}</h2>
              <p>
                {t("demandApproved.insight.generated", {
                  date: formatDate(detail.aiInsight.generatedAt)
                })}
              </p>
            </div>
          </div>
          <DataStatusBadge status={detail.aiInsight.dataStatus} />
          <blockquote>{localize(detail.aiInsight.text, locale)}</blockquote>
          <small>
            {t("demandApproved.insight.confidence", {
              value:
                detail.aiInsight.confidence == null
                  ? t("demandApproved.common.notAvailable")
                  : Math.round(detail.aiInsight.confidence * 100)
            })}
          </small>
        </section>
      )}

      {exportError && (
        <div className="demand-approved-toast">
          <Toast
            variant="error"
            message={t("demandApproved.export.failed")}
            onClose={clearExportError}
          />
        </div>
      )}
    </BusinessPageContainer>
  );
}

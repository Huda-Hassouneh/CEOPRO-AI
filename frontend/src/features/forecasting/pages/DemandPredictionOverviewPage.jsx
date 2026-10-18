import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { routePaths } from "../../../app/router/routePaths.js";
import { useAuthStore } from "../../auth/store/authStore.js";
import BusinessPageContainer from "../../../shared/components/layout/BusinessPageContainer.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { DemandPredictionTabs } from "../components/DemandPredictionTabs.jsx";
import { ForecastGenerationPanel } from "../components/ForecastGenerationPanel.jsx";
import { ForecastRefreshNotice } from "../components/ForecastRefreshNotice.jsx";
import { isForecastRefreshBusy } from "../utils/forecastRefresh.js";
import { ForecastCoverage } from "../components/ForecastCoverage.jsx";
import { DemandDataSection } from "../components/DemandDataSection.jsx";
import { DemandForecastChart } from "../components/DemandForecastChart.jsx";
import { DemandForecastTable } from "../components/DemandForecastTable.jsx";
import { DemandMetricCard } from "../components/DemandMetricCard.jsx";
import { DemandStatusBadge } from "../components/DemandStatusBadge.jsx";
import { useDemandPdfExport } from "../hooks/useDemandPdfExport.js";
import { useDemandPrediction } from "../hooks/useDemandPrediction.js";
import {
  forecastFormatters,
  localize
} from "../utils/forecastFormatters.js";
import "../styles/DemandPrediction.css";

export function DemandPredictionOverviewPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const tenantId = useAuthStore((state) => state.tenantId);
  const [productId, setProductId] = useState("all");
  const [periodDays, setPeriodDays] = useState(30);
  const query = useDemandPrediction({ productId, periodDays });
  const data = query.data;

  const { formatNumber, formatDate, formatRange } = useMemo(
    () => forecastFormatters(locale),
    [locale]
  );

  const canExport = Boolean(
    data &&
      !query.isFetching &&
      !query.isError &&
      !query.isPlaceholderData &&
      data.filters?.productId === productId &&
      data.filters?.periodDays === periodDays
  );

  const {
    exporting,
    exportError,
    clearExportError,
    requestExport
  } = useDemandPdfExport({
    data,
    locale,
    scope: `${tenantId}:${productId}:${periodDays}:overview`,
    enabled: canExport
  });

  if (query.isPending) {
    return (
      <div className="demand-approved-loading" aria-busy="true">
        <Skeleton height="70px" variant="rectangular" />
        <div>
          {Array.from({ length: 5 }, (_, index) => (
            <Skeleton key={index} height="120px" variant="rectangular" />
          ))}
        </div>
        <Skeleton height="300px" variant="rectangular" />
      </div>
    );
  }

  if (query.isError && !isForecastRefreshBusy(query)) {
    const accessDenied = query.error?.response?.status === 403;
    return (
      <EmptyState
        title={t("demandApproved.error.title")}
        description={accessDenied ? t("demandApproved.error.access") : getApiErrorMessage(query.error, t)}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("demandApproved.actions.retry")}
          </Button>
        }
      />
    );
  }

  if (!data?.products?.length) {
    return (
      <EmptyState
        title={t("demandApproved.empty.productsTitle")}
        description={t("demandApproved.empty.productsDescription")}
      />
    );
  }

  const selectedRow = data.forecasts?.find((row) => row.id === productId);
  const columns = [
    {
      key: "name",
      label: t("demandApproved.table.product"),
      render: (row) => localize(row.name, locale)
    },
    {
      key: "category",
      label: t("demandApproved.table.category"),
      render: (row) => localize(row.category, locale)
    },
    {
      key: "currentStock",
      label: t("demandApproved.table.currentStock"),
      render: (row) => formatNumber(row.currentStock)
    },
    {
      key: "expectedDemand",
      label: t("demandApproved.table.expectedDemand"),
      render: (row) => formatNumber(row.expectedDemand)
    },
    {
      key: "targetDate",
      label: t("demandApproved.table.targetDate"),
      render: (row) => formatDate(row.targetDate)
    },
    {
      key: "confidenceRange",
      label: t("demandApproved.table.confidenceRange"),
      render: (row) => formatRange(row.confidenceRange)
    },
    {
      key: "trend",
      label: t("demandApproved.table.trend"),
      render: (row) => (
        <DemandStatusBadge
          value={row.trend}
          namespace="demandApproved.trends"
          t={t}
        />
      )
    },
    {
      key: "recommendedAction",
      label: t("demandApproved.table.recommendedAction"),
      render: (row) => (
        <DemandStatusBadge
          value={row.recommendedAction}
          namespace="demandApproved.recommendations"
          t={t}
        />
      )
    },
    { key: "coverage", label: t("demandApproved.coverage.label"), render: (row) => <ForecastCoverage coverage={row.coverage} periodDays={periodDays} t={t} /> },
    { key: "generatedAt", label: t("demandApproved.history.generatedAt"), render: (row) => formatDate(row.forecastGeneratedAt) },
    {
      key: "actions",
      label: t("demandApproved.table.actions"),
      render: (row) => (
        <Button
          size="sm"
          variant="secondary"
          onClick={() =>
            navigate(
              `${routePaths.forecastProductDetail.replace(
                ":productId",
                encodeURIComponent(row.id)
              )}?periodDays=${periodDays}`
            )
          }
        >
          {t("demandApproved.actions.viewDetails")}
        </Button>
      )
    }
  ].filter((column) => column.key !== "recommendedAction" || data.featureAccess?.inventoryIntelligence === true);

  return (
    <BusinessPageContainer wide className="demand-approved-page" dir={dir}>
      <ForecastRefreshNotice query={query} t={t} />
      <PageHeader
        title={t("demandApproved.page.title")}
        subtitle={t("demandApproved.page.subtitle")}
        actions={
          <>
            <select
              className="demand-approved-select"
              aria-label={t("demandApproved.filters.product")}
              value={productId}
              onChange={(event) => setProductId(event.target.value)}
            >
              <option value="all">
                {t("demandApproved.filters.allProducts")}
              </option>
              {data.products.map((product) => (
                <option key={product.id} value={product.id}>
                  {localize(product.name, locale)}
                </option>
              ))}
            </select>
            <select
              className="demand-approved-select is-period"
              aria-label={t("demandApproved.filters.period")}
              value={periodDays}
              onChange={(event) => setPeriodDays(Number(event.target.value))}
            >
              {data.availablePeriods.map((period) => (
                <option key={period} value={period}>
                  {t(`demandApproved.filters.last${period}`)}
                </option>
              ))}
            </select>
          </>
        }
      />

      <DemandPredictionTabs t={t} inventoryAllowed={data.featureAccess?.inventoryIntelligence === true} />
      <ForecastGenerationPanel key={`${tenantId}:${productId}:${periodDays}`} productId={productId} periodDays={periodDays}
        coverage={selectedRow?.coverage} latestPrediction={selectedRow?.latestPrediction}
        generatedAt={selectedRow?.forecastGeneratedAt} locale={locale} t={t} refreshBlocked={isForecastRefreshBusy(query)} />
      <p className="forecast-coverage-note">{t("demandApproved.coverage.productCount", {
        covered: data.forecasts?.filter((row) => row.coverage?.status === "complete").length ?? 0,
        total: data.forecasts?.length ?? 0
      })} {t("demandApproved.coverage.note")}</p>
      <section
        className="demand-approved-metrics"
        aria-label={t("demandApproved.metrics.label")}
      >
        {data.metrics.map((metric) => {
          const label =
            metric.id === "next30Forecast"
              ? t("demandApproved.metrics.selectedForecast", {
                  days: periodDays
                })
              : t(`demandApproved.metrics.${metric.id}`);
          const value =
            metric.id === "next30Forecast" && metric.value != null
              ? `${formatNumber(metric.value)} ${t(
                  "demandApproved.common.units"
                )}`
              : formatNumber(metric.value);

          return (
            <DemandMetricCard
              key={metric.id}
              metric={metric}
              label={label}
              value={value}
            />
          );
        })}
      </section>

      <p className="forecast-coverage-note">{t("demandApproved.coverage.chartNote")}</p>
      <DemandDataSection
        title={t("demandApproved.chart.totalTitle")}
        subtitle={t("demandApproved.chart.totalSubtitle", {
          days: formatNumber(periodDays)
        })}
        dataStatus={data.totalForecast?.dataStatus}
        className="demand-approved-chart-panel"
      >
        <DemandForecastChart
          points={data.totalForecast?.points ?? []}
          t={t}
          formatDate={formatDate}
          formatNumber={formatNumber}
        />
      </DemandDataSection>

      <DemandDataSection
        title={t("demandApproved.forecasts.title")}
        subtitle={t("demandApproved.forecasts.subtitle")}
        dataStatus={data.sectionStatuses?.forecasts}
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
          className="is-main"
          columns={columns}
          rows={data.forecasts ?? []}
          emptyState={
            <EmptyState
              title={t("demandApproved.empty.forecastsTitle")}
              description={t("demandApproved.empty.forecastsDescription")}
            />
          }
        />
      </DemandDataSection>

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

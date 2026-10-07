import { useMemo, useState } from "react";
import {
  CalendarDays,
  Package,
  Search,
  SlidersHorizontal
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
import { routePaths } from "../../../app/router/routePaths.js";
import BusinessPageContainer from "../../../shared/components/layout/BusinessPageContainer.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import DataStatusBadge from "../../../shared/components/ui/DataStatusBadge.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { DemandPredictionTabs } from "../components/DemandPredictionTabs.jsx";
import { DemandKpiCard } from "../components/DemandShared.jsx";
import { DemandStatusBadge } from "../components/DemandStatusBadge.jsx";
import { useDemandPrediction } from "../hooks/useDemandPrediction.js";
import {
  forecastFormatters,
  localize
} from "../utils/forecastFormatters.js";
import "../styles/DemandPrediction.css";

const metricIcon = {
  next30Forecast: "calendar",
  productsForecasted: "package",
  predictedIncrease: "trendUp",
  predictedDecrease: "trendDown",
  stableDemand: "stable"
};

export function ProductForecastsListPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const [queryText, setQueryText] = useState("");
  const [category, setCategory] = useState("all");
  const [trend, setTrend] = useState("all");
  const [periodDays, setPeriodDays] = useState(30);
  const [page, setPage] = useState(1);
  const query = useDemandPrediction({ productId: "all", periodDays });
  const data = query.data;
  const { formatNumber } = useMemo(
    () => forecastFormatters(locale),
    [locale]
  );

  const categories = useMemo(() => {
    const values = new Set(
      (data?.forecasts ?? [])
        .map((row) => localize(row.category, locale))
        .filter((value) => value && value !== "—")
    );
    return [...values].sort((a, b) => a.localeCompare(b, locale));
  }, [data, locale]);

  const rows = useMemo(() => {
    const needle = queryText.trim().toLocaleLowerCase(locale);
    return (data?.forecasts ?? []).filter((row) => {
      const name = localize(row.name, locale);
      const rowCategory = localize(row.category, locale);
      const matchesQuery =
        !needle ||
        `${name} ${rowCategory}`.toLocaleLowerCase(locale).includes(needle);
      const matchesCategory = category === "all" || rowCategory === category;
      const matchesTrend = trend === "all" || row.trend === trend;
      return matchesQuery && matchesCategory && matchesTrend;
    });
  }, [data, queryText, category, trend, locale]);

  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const currentPage = Math.min(page, pageCount);
  const pageRows = rows.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize
  );

  const clear = () => {
    setQueryText("");
    setCategory("all");
    setTrend("all");
    setPage(1);
  };

  if (query.isPending) {
    return (
      <div className="demand-approved-loading" aria-busy="true">
        <Skeleton height="70px" variant="rectangular" />
        <Skeleton height="400px" variant="rectangular" />
      </div>
    );
  }

  if (query.isError) {
    return (
      <EmptyState
        title={t("demandApproved.error.title")}
        description={query.error?.response?.status === 403 ? t("demandApproved.error.access") : getApiErrorMessage(query.error, t)}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("demandApproved.actions.retry")}
          </Button>
        }
      />
    );
  }

  const kpis = (data?.metrics ?? []).map((metric) => ({
    icon: metricIcon[metric.id] ?? "package",
    labelKey:
      metric.id === "next30Forecast"
        ? "demandApproved.metrics.next30Forecast"
        : `demandApproved.metrics.${metric.id}`,
    value:
      metric.id === "next30Forecast" && metric.value != null
        ? `${formatNumber(metric.value)} ${t("demandApproved.common.units")}`
        : formatNumber(metric.value)
  }));

  return (
    <BusinessPageContainer wide className="demand-page demand-products-page">
      <PageHeader
        title={t("demand.products.title")}
        subtitle={t("demand.products.subtitle")}
        actions={
          <label className="demand-date-control">
            <CalendarDays size={15} />
            <select
              aria-label={t("demand.common.dateRange")}
              value={periodDays}
              onChange={(event) => {
                setPeriodDays(Number(event.target.value));
                setPage(1);
              }}
            >
              {(data?.availablePeriods ?? [7, 30]).map((period) => (
                <option key={period} value={period}>
                  {t(`demandApproved.filters.last${period}`)}
                </option>
              ))}
            </select>
          </label>
        }
      />

      <DemandPredictionTabs t={t} />

      <section className="demand-kpi-grid demand-product-summary">
        {kpis.map((item) => (
          <DemandKpiCard key={item.labelKey} item={item} t={t} />
        ))}
      </section>

      <div className="demand-filter-row">
        <label className="demand-search">
          <Search size={16} />
          <input
            value={queryText}
            onChange={(event) => {
              setQueryText(event.target.value);
              setPage(1);
            }}
            placeholder={t("demand.filters.searchProducts")}
            aria-label={t("demand.filters.searchProducts")}
          />
        </label>

        <select
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            setPage(1);
          }}
          aria-label={t("demand.filters.category")}
        >
          <option value="all">{t("demand.filters.allCategories")}</option>
          {categories.map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </select>

        <select
          value={trend}
          onChange={(event) => {
            setTrend(event.target.value);
            setPage(1);
          }}
          aria-label={t("demand.filters.trend")}
        >
          <option value="all">{t("demand.filters.allTrends")}</option>
          <option value="increasing">
            {t("demandApproved.trends.increasing")}
          </option>
          <option value="decreasing">
            {t("demandApproved.trends.decreasing")}
          </option>
          <option value="stable">{t("demandApproved.trends.stable")}</option>
        </select>

        <button type="button" className="demand-clear" onClick={clear}>
          <SlidersHorizontal size={15} />
          {t("demand.filters.clear")}
        </button>
      </div>

      <section className="demand-table-panel">
        {pageRows.length ? (
          <div className="demand-table-wrap">
            <table className="demand-table demand-products-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>{t("demand.table.product")}</th>
                  <th>{t("demand.table.category")}</th>
                  <th>{t("demand.table.currentStock")}</th>
                  <th>{t("demand.table.forecast30")}</th>
                  <th>{t("demand.table.change")}</th>
                  <th>{t("demand.table.demandTrend")}</th>
                  <th>{t("demand.table.accuracy")}</th>
                  <th>{t("demand.table.status")}</th>
                  <th>{t("demand.table.action")}</th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((product, index) => (
                  <tr key={product.id}>
                    <td>{(currentPage - 1) * pageSize + index + 1}</td>
                    <td>
                      <div className="demand-product">
                        <span className="demand-product__thumb">
                          <Package size={24} />
                        </span>
                        <div>
                          <strong>{localize(product.name, locale)}</strong>
                        </div>
                      </div>
                    </td>
                    <td>{localize(product.category, locale)}</td>
                    <td><bdi>{formatNumber(product.currentStock)}</bdi></td>
                    <td><bdi>{formatNumber(product.expectedDemand)}</bdi></td>
                    <td>—</td>
                    <td>
                      <DemandStatusBadge
                        value={product.trend}
                        namespace="demandApproved.trends"
                        t={t}
                      />
                    </td>
                    <td>
                      {product.modelAccuracy == null
                        ? "—"
                        : `${formatNumber(product.modelAccuracy)}%`}
                    </td>
                    <td>
                      {product.dataStatus ? (
                        <DataStatusBadge status={product.dataStatus} />
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() =>
                          navigate(
                            `${routePaths.forecastProductDetail.replace(
                              ":productId",
                              encodeURIComponent(product.id)
                            )}?periodDays=${periodDays}`
                          )
                        }
                      >
                        {t("demand.common.viewDetails")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState title={t("demand.products.empty")} />
        )}

        <div className="demand-pagination">
          <span>
            {t("demand.products.showing", {
              count: rows.length,
              total: data?.forecasts?.length ?? 0
            })}
          </span>
          <div>
            <button
              type="button"
              aria-label={t("demand.pagination.previous")}
              disabled={currentPage <= 1}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            >
              ‹
            </button>
            <button className="is-active" type="button">
              {currentPage}
            </button>
            <button
              type="button"
              aria-label={t("demand.pagination.next")}
              disabled={currentPage >= pageCount}
              onClick={() =>
                setPage((value) => Math.min(pageCount, value + 1))
              }
            >
              ›
            </button>
          </div>
        </div>
      </section>
    </BusinessPageContainer>
  );
}

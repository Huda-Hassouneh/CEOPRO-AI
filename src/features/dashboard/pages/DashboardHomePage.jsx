import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Cell,
  CartesianGrid,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis
} from "recharts";
import { ArrowUpRight, Database } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import { useAuthStore } from "../../auth/store/authStore.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Modal from "../../../shared/components/ui/Modal.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import DataStatusBadge from "../../../shared/components/ui/DataStatusBadge.jsx";
import { KpiCard } from "../components/KpiCard.jsx";
import { DashboardChartCard } from "../components/DashboardChartCard.jsx";
import { DashboardTableCard } from "../components/DashboardTableCard.jsx";
import { DashboardStateBoundary } from "../components/DashboardStateBoundary.jsx";
import { useDashboardAggregate } from "../hooks/useDashboardAggregate.js";
import { getMockDashboard } from "../mocks/dashboardMockData.js";
import "../styles/Dashboard.css";

const INVENTORY_COLORS = ["#4f46e5", "#f59e0b", "#ef476f"];

export function localize(value, locale) {
  if (value && typeof value === "object")
    return value[locale] || value.en || Object.values(value)[0];
  return value;
}

function DataTable({ columns, rows, emptyState }) {
  if (!rows?.length) return emptyState;
  return (
    <div className="dashboard-table-wrap">
      <table className="dashboard-data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render ? column.render(row) : row[column.key]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ActivityStatus({ status, t }) {
  return (
    <span className={`dashboard-activity-status is-${status}`}>
      <i aria-hidden="true" />
      {t(`dashboard.activity.statuses.${status}`)}
    </span>
  );
}

export function DashboardHomePage({ status, dashboardData }) {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const companyId = useAuthStore((state) => state.tenantId);
  const [days, setDays] = useState(30);
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const dashboardQuery = useDashboardAggregate(days, companyId);
  const dashboard =
    dashboardData || dashboardQuery.data || getMockDashboard(days);
  const effectiveStatus =
    status ||
    (dashboardQuery.isPending
      ? "loading"
      : dashboardQuery.isError
        ? "error"
        : dashboard
          ? "ready"
          : "empty");

  const numberFormatter = useMemo(
    () => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    [locale]
  );
  const currencyFormatter = useMemo(
    () =>
      new Intl.NumberFormat(locale, {
        style: "currency",
        currency: dashboard.company.currency,
        maximumFractionDigits: 0
      }),
    [dashboard.company.currency, locale]
  );
  const compactCurrencyFormatter = useMemo(
    () =>
      new Intl.NumberFormat(locale, {
        style: "currency",
        currency: dashboard.company.currency,
        notation: "compact",
        maximumFractionDigits: 1
      }),
    [dashboard.company.currency, locale]
  );
  const dateFormatter = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "short",
        day: "numeric",
        timeZone: "UTC"
      }),
    [locale]
  );
  const formatDate = (value) =>
    dateFormatter.format(new Date(`${value}T00:00:00Z`));
  const formatMetric = (metric) => {
    if (metric.formattedValue) return localize(metric.formattedValue, locale);
    if (metric.format === "currency")
      return currencyFormatter.format(metric.value);
    if (metric.format === "percent")
      return `${numberFormatter.format(metric.value)}%`;
    if (metric.format === "signedPercent")
      return `${metric.value > 0 ? "+" : ""}${numberFormatter.format(metric.value)}%`;
    if (metric.format === "sentiment")
      return t(`dashboard.sentiment.${metric.value}`);
    return numberFormatter.format(metric.value);
  };

  const emptyState = (titleKey, descriptionKey, connect = false) => (
    <EmptyState
      className="dashboard-inline-empty"
      icon={<Database size={24} />}
      title={t(titleKey)}
      description={t(descriptionKey)}
      action={
        connect ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => navigate(routePaths.connectData)}
          >
            {t("dashboard.controls.connectData")}
          </Button>
        ) : undefined
      }
    />
  );
  const inventoryRows = dashboard.inventoryStatus?.items || [];
  const activityRows = dashboard.recentActivity?.rows || [];
  const inventoryChart = dashboard.inventoryStatus
    ? [
        {
          name: t("dashboard.inventory.inStock"),
          value: dashboard.inventoryStatus.totals.inStock
        },
        {
          name: t("dashboard.inventory.lowStock"),
          value: dashboard.inventoryStatus.totals.lowStock
        },
        {
          name: t("dashboard.inventory.outOfStock"),
          value: dashboard.inventoryStatus.totals.outOfStock
        }
      ]
    : [];

  const productColumn = {
    key: "product",
    label: t("dashboard.tables.product"),
    render: (row) => localize(row.product, locale)
  };
  const activityColumns = [
    {
      key: "date",
      label: t("dashboard.activity.date"),
      render: (row) => formatDate(row.date)
    },
    {
      key: "activity",
      label: t("dashboard.activity.activity"),
      render: (row) => localize(row.activity, locale)
    },
    {
      key: "details",
      label: t("dashboard.activity.details"),
      render: (row) => localize(row.details, locale)
    },
    {
      key: "status",
      label: t("dashboard.activity.status"),
      render: (row) => <ActivityStatus status={row.status} t={t} />
    }
  ];

  return (
    <DashboardStateBoundary
      status={effectiveStatus}
      title={t("dashboard.page.title")}
      onRetry={dashboardQuery.refetch}
    >
      <div className="dashboard-page" dir={dir}>
        <PageHeader
          title={t("dashboard.page.title")}
          subtitle={t("dashboard.page.subtitle")}
          actions={
            <label className="dashboard-period-control">
              <span>{t("dashboard.controls.dateRange")}</span>
              <select
                className="dashboard-date-select"
                value={days}
                onChange={(event) => setDays(Number(event.target.value))}
              >
                {dashboard.availablePeriods.map((period) => (
                  <option key={period} value={period}>
                    {t(`dashboard.controls.last${period}`)}
                  </option>
                ))}
              </select>
            </label>
          }
        />

        <section
          className="dashboard-kpi-grid"
          aria-label={t("dashboard.sections.kpis")}
        >
          {dashboard.metrics.map((metric) => (
            <KpiCard
              key={metric.id}
              metric={{ ...metric, formattedValue: formatMetric(metric) }}
              label={t(metric.labelKey)}
            />
          ))}
        </section>

        <section className="dashboard-section dashboard-overview-grid">
          <DashboardChartCard
            title={t("dashboard.sales.title")}
            subtitle={t("dashboard.sales.subtitle", {
              days: numberFormatter.format(days),
              currency:
                dashboard.salesOverview?.currency || dashboard.company.currency
            })}
            dataStatus={dashboard.salesOverview?.dataStatus}
          >
            {dashboard.salesOverview?.points?.length ? (
              <div className="dashboard-sales-chart" dir="ltr">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={dashboard.salesOverview.points}
                    margin={{ top: 12, right: 12, left: 0, bottom: 0 }}
                  >
                    <defs>
                      <linearGradient
                        id="salesLineGradient"
                        x1="0"
                        y1="0"
                        x2="1"
                        y2="0"
                      >
                        <stop offset="0%" stopColor="#7c6cf3" />
                        <stop offset="100%" stopColor="#2f2bce" />
                      </linearGradient>
                    </defs>
                    <CartesianGrid
                      vertical={false}
                      stroke="#ebeaf5"
                      strokeDasharray="3 3"
                    />
                    <XAxis
                      dataKey="date"
                      tickFormatter={formatDate}
                      tickLine={false}
                      axisLine={false}
                      minTickGap={32}
                      tick={{ fontSize: 10, fill: "#7a7d8d" }}
                    />
                    <YAxis
                      tickFormatter={(value) =>
                        compactCurrencyFormatter.format(value)
                      }
                      width={58}
                      tickLine={false}
                      axisLine={false}
                      tick={{ fontSize: 10, fill: "#7a7d8d" }}
                    />
                    <ChartTooltip
                      labelFormatter={formatDate}
                      formatter={(value) => [
                        currencyFormatter.format(value),
                        t("dashboard.sales.tooltip")
                      ]}
                      contentStyle={{
                        borderRadius: 10,
                        borderColor: "#dfe3f1",
                        fontSize: 12
                      }}
                    />
                    <Line
                      type="monotone"
                      dataKey="value"
                      stroke="url(#salesLineGradient)"
                      strokeWidth={2.5}
                      dot={false}
                      activeDot={{ r: 4, fill: "#2f2bce" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : (
              emptyState(
                "dashboard.empty.salesTitle",
                "dashboard.empty.salesDescription"
              )
            )}
          </DashboardChartCard>

          <DashboardChartCard
            title={t("dashboard.inventory.title")}
            subtitle={t("dashboard.inventory.subtitle")}
            dataStatus={dashboard.inventoryStatus?.dataStatus}
          >
            {dashboard.inventoryStatus ? (
              <>
                <div className="dashboard-inventory-visual">
                  <div className="dashboard-donut" dir="ltr">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={inventoryChart}
                          dataKey="value"
                          nameKey="name"
                          innerRadius={54}
                          outerRadius={72}
                          paddingAngle={2}
                          stroke="none"
                        >
                          {inventoryChart.map((entry, index) => (
                            <Cell
                              key={entry.name}
                              fill={INVENTORY_COLORS[index]}
                            />
                          ))}
                        </Pie>
                        <ChartTooltip
                          formatter={(value, name) => [
                            numberFormatter.format(value),
                            name
                          ]}
                          contentStyle={{
                            borderRadius: 10,
                            borderColor: "#dfe3f1",
                            fontSize: 12
                          }}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                    <div className="dashboard-donut__total">
                      <strong>
                        {numberFormatter.format(
                          dashboard.inventoryStatus.totals.totalItems
                        )}
                      </strong>
                      <span>{t("dashboard.inventory.totalItems")}</span>
                    </div>
                  </div>
                  <div className="dashboard-inventory-legend">
                    {inventoryChart.map((item, index) => (
                      <div key={item.name}>
                        <i style={{ background: INVENTORY_COLORS[index] }} />
                        <span>{item.name}</span>
                        <strong>{numberFormatter.format(item.value)}</strong>
                      </div>
                    ))}
                  </div>
                </div>
                <button
                  type="button"
                  className="dashboard-link dashboard-card-action"
                  onClick={() => setInventoryOpen(true)}
                >
                  {t("dashboard.inventory.view")}
                  <ArrowUpRight size={14} />
                </button>
              </>
            ) : (
              emptyState(
                "dashboard.empty.inventoryTitle",
                "dashboard.empty.inventoryDescription",
                true
              )
            )}
          </DashboardChartCard>
        </section>

        <section className="dashboard-section dashboard-table-grid">
          <DashboardTableCard
            title={t("dashboard.forecast.title")}
            subtitle={t("dashboard.forecast.subtitle")}
            dataStatus={dashboard.demandForecast?.dataStatus}
            actionLabel={t("dashboard.forecast.view")}
            onAction={() => navigate(routePaths.forecasts)}
          >
            <DataTable
              columns={[
                productColumn,
                {
                  key: "forecastedDemand",
                  label: t("dashboard.tables.forecastedDemand"),
                  render: (row) => numberFormatter.format(row.forecastedDemand)
                }
              ]}
              rows={dashboard.demandForecast?.rows}
              emptyState={emptyState(
                "dashboard.empty.forecastTitle",
                "dashboard.empty.forecastDescription"
              )}
            />
          </DashboardTableCard>
          <DashboardTableCard
            title={t("dashboard.competitors.title")}
            subtitle={t("dashboard.competitors.subtitle")}
            dataStatus={dashboard.competitorComparison?.dataStatus}
            actionLabel={t("dashboard.competitors.view")}
            onAction={() => navigate(routePaths.marketCompetitors)}
          >
            <DataTable
              columns={[
                productColumn,
                {
                  key: "ourPrice",
                  label: t("dashboard.tables.ourPrice"),
                  render: (row) => currencyFormatter.format(row.ourPrice)
                },
                {
                  key: "lowestCompetitorPrice",
                  label: t("dashboard.tables.competitorPrice"),
                  render: (row) =>
                    currencyFormatter.format(row.lowestCompetitorPrice)
                }
              ]}
              rows={dashboard.competitorComparison?.rows}
              emptyState={emptyState(
                "dashboard.empty.competitorsTitle",
                "dashboard.empty.competitorsDescription"
              )}
            />
          </DashboardTableCard>
        </section>

        <section className="dashboard-section dashboard-panel dashboard-activity-card">
          <div className="dashboard-panel__header">
            <div>
              <h2>{t("dashboard.activity.title")}</h2>
              <p>{t("dashboard.activity.subtitle")}</p>
            </div>
            <button
              type="button"
              className="dashboard-link"
              onClick={() => setActivityOpen(true)}
            >
              {t("dashboard.controls.viewAll")}
              <ArrowUpRight size={14} />
            </button>
          </div>
          <DataTable
            columns={activityColumns}
            rows={activityRows.slice(0, 4)}
            emptyState={emptyState(
              "dashboard.empty.activityTitle",
              "dashboard.empty.activityDescription"
            )}
          />
        </section>

        <Modal
          isOpen={inventoryOpen}
          onClose={() => setInventoryOpen(false)}
          title={t("dashboard.inventory.detailsTitle")}
          closeLabel={t("common.close")}
          maxWidth="720px"
        >
          <div className="dashboard-modal-heading">
            <p>{t("dashboard.inventory.detailsSubtitle")}</p>
            {dashboard.inventoryStatus && (
              <DataStatusBadge status={dashboard.inventoryStatus.dataStatus} />
            )}
          </div>
          <DataTable
            columns={[
              productColumn,
              {
                key: "quantity",
                label: t("dashboard.tables.quantity"),
                render: (row) => numberFormatter.format(row.quantity)
              }
            ]}
            rows={inventoryRows}
            emptyState={emptyState(
              "dashboard.empty.inventoryTitle",
              "dashboard.empty.inventoryDescription",
              true
            )}
          />
        </Modal>
        <Modal
          isOpen={activityOpen}
          onClose={() => setActivityOpen(false)}
          title={t("dashboard.activity.historyTitle")}
          closeLabel={t("common.close")}
          maxWidth="920px"
        >
          <DataTable
            columns={activityColumns}
            rows={activityRows}
            emptyState={emptyState(
              "dashboard.empty.activityTitle",
              "dashboard.empty.activityDescription"
            )}
          />
        </Modal>
      </div>
    </DashboardStateBoundary>
  );
}

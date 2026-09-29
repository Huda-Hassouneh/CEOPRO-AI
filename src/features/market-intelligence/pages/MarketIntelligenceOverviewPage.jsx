import { useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { routePaths } from "../../../app/router/routePaths.js";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import Toast from "../../../shared/components/ui/Toast.jsx";
import { AiMarketIntelligencePanel } from "../components/AiMarketIntelligencePanel.jsx";
import { ExpansionOpportunityCard } from "../components/ExpansionOpportunityCard.jsx";
import { MarketIntelligenceMetricCard } from "../components/MarketIntelligenceMetricCard.jsx";
import { MarketIntelligenceSection } from "../components/MarketIntelligenceSection.jsx";
import { MarketIntelligenceTable } from "../components/MarketIntelligenceTable.jsx";
import { useMarketIntelligenceOverview } from "../hooks/useMarketIntelligenceOverview.js";
import "../styles/MarketIntelligence.css";
import { LeaderboardTable } from "../components/LeaderboardTable.jsx";
function localizeValue(value, locale) {
  if (value && typeof value === "object")
    return value[locale] || value.en || Object.values(value)[0];
  return value;
}

function ToneBadge({ value, namespace }) {
  return (
    <span className={`market-main-badge is-${value}`}>{namespace(value)}</span>
  );
}

export function MarketIntelligenceOverviewPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const [productId, setProductId] = useState(null);
  const [periodDays, setPeriodDays] = useState(30);
  const [exportNotice, setExportNotice] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const exportInProgress = useRef(false);
  const query = useMarketIntelligenceOverview({
    productId,
    periodDays
  });

  const data = query.data;

  const number = useMemo(
    () => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }),
    [locale]
  );
  const date = useMemo(
    () =>
      new Intl.DateTimeFormat(locale, {
        month: "short",
        day: "numeric",
        year: "numeric",
        timeZone: "UTC"
      }),
    [locale]
  );
  const moneyFormatters = useMemo(() => new Map(), [locale]);
  const localize = (value) => localizeValue(value, locale);
  const formatDate = (value) => {
    if (!value) return "—";
    const parsed = new Date(value.includes("T") ? value : `${value}T00:00:00Z`);
    return Number.isNaN(parsed.getTime()) ? "—" : date.format(parsed);
  };
  const money = (value, currency) => {
    if (value == null) return "—";
    if (!moneyFormatters.has(currency))
      moneyFormatters.set(
        currency,
        new Intl.NumberFormat(locale, {
          style: "currency",
          currency
        })
      );
    return moneyFormatters.get(currency).format(value);
  };
  const requestExport = async (section) => {
    if (exportInProgress.current || query.isFetching || !data) return;
    exportInProgress.current = true;
    setIsExporting(true);
    setExportNotice(false);
    try {
      const { exportMarketIntelligencePdf } = await import("../utils/exportMarketIntelligencePdf.js");
      await exportMarketIntelligencePdf({ data, section, locale, periodDays });
    } catch (error) {
      console.error("Market Intelligence PDF export failed:", error);
      setExportNotice(true);
    } finally {
      exportInProgress.current = false;
      setIsExporting(false);
    }
  };
  const empty = (titleKey, descriptionKey, action) => (
    <EmptyState
      className="market-main-empty"
      title={t(titleKey)}
      description={t(descriptionKey)}
      action={action}
    />
  );

  if (query.isPending)
    return (
      <div className="market-main-loading" aria-busy="true">
        <Skeleton height="72px" variant="rectangular" />
        <div>
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} height="122px" variant="rectangular" />
          ))}
        </div>
        <Skeleton height="300px" variant="rectangular" />
      </div>
    );
  if (query.isError)
    return (
      <EmptyState
        title={t("marketMain.error.title")}
        description={t("marketMain.error.description")}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("marketMain.actions.retry")}
          </Button>
        }
      />
    );
  if (!data?.products?.length)
    return (
      <EmptyState
        title={t("marketMain.empty.productsTitle")}
        description={t("marketMain.empty.productsDescription")}
        action={
          <Button size="sm" onClick={() => navigate(routePaths.connectData)}>
            {t("marketMain.actions.connectData")}
          </Button>
        }
      />
    );

  const selectedProduct = data.selectedProduct;
  const currency = selectedProduct?.currency?.toUpperCase() || "JOD";
  const productName = (row) => localize(row.productName);
  const formatMetric = (metric) => {
    if (metric.value == null) return "—";

    if (metric.format === "score100") {
      return `${number.format(metric.value)} / 100`;
    }

    if (metric.format === "score10") {
      return `${number.format(metric.value)} / 10`;
    }

    return number.format(metric.value);
  };
  const productColumn = {
    key: "product",
    label: t("marketMain.tables.product"),
    render: productName
  };
  const competitorColumns = [
    productColumn,
    { key: "competitorName", label: t("marketMain.tables.competitor") },
    {
      key: "pricingScore",
      label: t("marketMain.tables.pricingScore"),
      render: (row) => row.pricingScore == null ? "—" : `${number.format(row.pricingScore)} / 10`
    },
    {
      key: "compositeScore",
      label: t("marketMain.tables.compositeScore"),
      render: (row) => row.compositeScore == null ? "—" : `${number.format(row.compositeScore)} / 100`
    },
    {
      key: "relevanceScore",
      label: t("marketMain.tables.relevanceScore"),
      render: (row) => row.relevanceScore == null ? "—" : `${number.format(row.relevanceScore)} / 100`
    },
    {
      key: "marketPresenceScore",
      label: t("marketMain.tables.presenceScore"),
      render: (row) => row.marketPresenceScore == null ? "—" : `${number.format(row.marketPresenceScore)} / 100`
    },
    {
      key: "marketPerception",
      label: t("marketMain.tables.perception"),
      render: (row) => row.marketPerception == null ? "—" : (
        <ToneBadge
          value={row.marketPerception}
          namespace={(value) => t(`marketMain.sentiments.${value}`)}
        />
      )
    }
  ];
  const pricingColumns = [
    productColumn,
    {
      key: "currentPrice",
      label: t("marketMain.tables.currentPrice"),
      render: (row) => money(row.currentPrice, currency)
    },
    {
      key: "action",
      label: t("marketMain.tables.action"),
      render: (row) => (
        <ToneBadge
          value={row.action}
          namespace={(value) => t(`marketMain.actions.${value}`)}
        />
      )
    },
    {
      key: "suggestedPrice",
      label: t("marketMain.tables.suggestedPrice"),
      render: (row) => money(row.suggestedPrice, currency)
    },
    {
      key: "marketMin",
      label: t("marketMain.tables.marketMin"),
      render: (row) => money(row.marketMin, currency)
    },
    {
      key: "marketMax",
      label: t("marketMain.tables.marketMax"),
      render: (row) => money(row.marketMax, currency)
    },
    {
      key: "marketAverage",
      label: t("marketMain.tables.marketAverage"),
      render: (row) => money(row.marketAverage, currency)
    },
    {
      key: "marketMedian",
      label: t("marketMain.tables.marketMedian"),
      render: (row) => money(row.marketMedian, currency)
    },
    {
      key: "matchedCompetitors",
      label: t("marketMain.tables.matchedCompetitors"),
      render: (row) => number.format(row.matchedCompetitors)
    },
    {
      key: "explanation",
      label: t("marketMain.tables.explanation"),
      className: "market-main-table__explanation",
      render: (row) => localize(row.explanation)
    }
  ];
  const changesColumns = [
    {
      key: "date",
      label: t("marketMain.tables.date"),
      render: (row) => formatDate(row.date)
    },
    { key: "competitor", label: t("marketMain.tables.competitor") },
    productColumn,
    {
      key: "previousPrice",
      label: t("marketMain.tables.previousPrice"),
      render: (row) => money(row.previousPrice, currency)
    },
    {
      key: "newPrice",
      label: t("marketMain.tables.newPrice"),
      render: (row) => money(row.newPrice, currency)
    },
    {
      key: "change",
      label: t("marketMain.tables.change"),
      render: (row) => (
        <span className={`market-main-change is-${row.direction}`}>
          {row.direction === "increased" ? (
            <ArrowUp size={13} />
          ) : (
            <ArrowDown size={13} />
          )}
          {money(Math.abs(row.newPrice - row.previousPrice), currency)}{" "}
          {t(`marketMain.changes.${row.direction}`)}
        </span>
      )
    },
    {
      key: "detectedAt",
      label: t("marketMain.tables.detected"),
      render: (row) => formatDate(row.detectedAt)
    }
  ];
  return (
    <div className="market-intelligence-main" dir={dir}>
      <PageHeader
        title={t("marketMain.page.title")}
        subtitle={t("marketMain.page.subtitle")}
        actions={
          <>
            <select
              className="market-main-select market-main-period"
              aria-label={t("marketMain.actions.dateRange")}
              value={periodDays}
              onChange={(event) => setPeriodDays(Number(event.target.value))}
            >
              {data.availablePeriods.map((period) => (
                <option key={period} value={period}>
                  {t(`market.controls.last${period}`)}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              leadingIcon={<Plus size={15} />}
              onClick={() => navigate(routePaths.marketAddCompetitor)}
            >
              {t("market.controls.addCompetitor")}
            </Button>
          </>
        }
      />

      <label className="market-main-product">
        <span>{t("marketMain.product.label")}</span>
        <select
          className="market-main-select"
          value={selectedProduct.id}
          onChange={(event) => setProductId(event.target.value)}
        >
          {data.products.map((product) => (
            <option key={product.id} value={product.id}>
              {localize(product.name)}
            </option>
          ))}
        </select>
      </label>

      <section
        className="market-main-metrics"
        aria-label={t("marketMain.metrics.label")}
      >
        {data.metrics.map((metric) => {
          return (
            <MarketIntelligenceMetricCard
              key={metric.id}
              metric={metric}
              label={t(`marketMain.metrics.${metric.id}`)}
              value={formatMetric(metric)}
            />
          );
        })}
      </section>

      <section>
        <AiMarketIntelligencePanel
          intelligence={data.aiMarketIntelligence}
          t={t}
          localize={localize}
          formatDate={formatDate}
          emptyState={empty(
            "marketMain.empty.aiTitle",
            "marketMain.empty.aiDescription"
          )}
        />
      </section>

      <MarketIntelligenceSection
        title={t("marketMain.competitors.title")}
        subtitle={t("marketMain.competitors.subtitle", {
          product: localize(selectedProduct.name)
        })}
        dataStatus={data.competitors[0]?.dataStatus}
        exportLabel={t("marketMain.actions.exportPdf")}
        exportDisabled={isExporting || query.isFetching}
        onExport={() => requestExport("competitors")}
      >
        <MarketIntelligenceTable
          className="is-competitors"
          columns={competitorColumns}
          rows={data.competitors}
          emptyState={empty(
            "marketMain.empty.competitorsTitle",
            "marketMain.empty.competitorsDescription",
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate(routePaths.marketAddCompetitor)}
            >
              {t("market.controls.addCompetitor")}
            </Button>
          )}
        />
      </MarketIntelligenceSection>

      <MarketIntelligenceSection
        title={t("marketMain.pricing.title")}
        subtitle={t("marketMain.pricing.subtitle")}
        dataStatus={data.pricingRecommendations[0]?.dataStatus}
        exportLabel={t("marketMain.actions.exportPdf")}
        exportDisabled={isExporting || query.isFetching}
        onExport={() => requestExport("pricing")}
      >
        <MarketIntelligenceTable
          className="is-pricing"
          columns={pricingColumns}
          rows={data.pricingRecommendations}
          emptyState={empty(
            "marketMain.empty.pricingTitle",
            "marketMain.empty.pricingDescription"
          )}
        />
      </MarketIntelligenceSection>

      <MarketIntelligenceSection
        title={t("marketMain.opportunities.title")}
        subtitle={t("marketMain.opportunities.subtitle")}
        dataStatus={data.expansionOpportunities[0]?.dataStatus}
        exportLabel={t("marketMain.actions.exportPdf")}
        exportDisabled={isExporting || query.isFetching}
        onExport={() => requestExport("opportunities")}
      >
        {data.expansionOpportunities.length ? (
          <div className="market-main-opportunity-grid">
            {data.expansionOpportunities.map((opportunity) => (
              <ExpansionOpportunityCard
                key={opportunity.id}
                opportunity={opportunity}
                t={t}
                localize={localize}
                number={number.format}
              />
            ))}
          </div>
        ) : (
          empty(
            "marketMain.empty.opportunitiesTitle",
            "marketMain.empty.opportunitiesDescription"
          )
        )}
      </MarketIntelligenceSection>

      <MarketIntelligenceSection
        title={t("marketMain.changes.title")}
        subtitle={t("marketMain.changes.subtitle")}
        dataStatus={data.recentPriceChanges[0]?.dataStatus}
        exportLabel={t("marketMain.actions.exportPdf")}
        exportDisabled={isExporting || query.isFetching}
        onExport={() => requestExport("price-changes")}
      >
        <MarketIntelligenceTable
          className="is-changes"
          columns={changesColumns}
          rows={data.recentPriceChanges}
          emptyState={empty(
            "marketMain.empty.changesTitle",
            "marketMain.empty.changesDescription"
          )}
        />
      </MarketIntelligenceSection>

      {exportNotice && (
        <div className="market-main-toast">
          <Toast
            variant="error"
            message={t("marketMain.export.failed")}
            onClose={() => setExportNotice(false)}
          />
        </div>
      )}
    </div>
  );
}

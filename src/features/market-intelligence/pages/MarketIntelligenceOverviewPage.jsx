import { useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Plus, RefreshCw } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { getApiErrorMessage } from "../../../shared/lib/apiErrors.js";
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
import { usePricingRecommendation } from "../hooks/usePricingRecommendation.js";
import "../styles/MarketIntelligence.css";

function localizeValue(value, locale) {
  if (value && typeof value === "object") {
    return value[locale] || value.en || Object.values(value)[0];
  }

  return value;
}

function ToneBadge({ value, namespace }) {
  if (!value) return "—";

  return (
    <span className={`market-main-badge is-${value}`}>{namespace(value)}</span>
  );
}

function buildPricingRows({ overviewRows, recommendation, selectedProduct }) {
  if (!selectedProduct) return [];

  const baseRow =
    overviewRows?.find((row) => row.productId === selectedProduct.id) ??
    overviewRows?.[0] ??
    null;

  if (!recommendation) {
    if (!baseRow) return [];

    return [
      {
        ...baseRow,
        action: null,
        suggestedPrice: null,
        matchedCompetitors: null,
        explanation: null,
        confidenceScore: null,
        guardrailClamped: null,
        marginGuardrailClamped: null,
        evidenceId: null,
        outcomeId: null
      }
    ];
  }

  return [
    {
      ...(baseRow ?? {}),
      id: `price-rec-${selectedProduct.id}`,
      productId: selectedProduct.id,
      productName: selectedProduct.name,
      status: recommendation.status,
      currentPrice:
        recommendation.current_price ?? baseRow?.currentPrice ?? null,
      action: recommendation.status === "OK" ? recommendation.action : null,
      suggestedPrice:
        recommendation.status === "OK" ? recommendation.suggested_price : null,
      marketMin: recommendation.market_min ?? baseRow?.marketMin ?? null,
      marketMax: recommendation.market_max ?? baseRow?.marketMax ?? null,
      marketAverage:
        recommendation.market_avg ?? baseRow?.marketAverage ?? null,
      marketMedian:
        recommendation.market_median ?? baseRow?.marketMedian ?? null,
      matchedCompetitors: recommendation.matched_competitor_count ?? null,
      explanation: recommendation.explanation ?? null,
      confidenceScore: recommendation.confidence_score ?? null,
      guardrailClamped: recommendation.guardrail_clamped ?? null,
      marginGuardrailClamped: recommendation.margin_guardrail_clamped ?? null,
      evidenceId: recommendation.evidence_id ?? null,
      outcomeId: recommendation.outcome_id ?? null,
      currency: recommendation.currency ?? selectedProduct.currency,
      dataStatus: recommendation.status === "OK" ? "derived" : "unavailable"
    }
  ];
}

export function MarketIntelligenceOverviewPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();

  const [productId, setProductId] = useState(null);
  const [periodDays, setPeriodDays] = useState(30);
  const [exportNotice, setExportNotice] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [pricingByProduct, setPricingByProduct] = useState({});

  const exportInProgress = useRef(false);

  const query = useMarketIntelligenceOverview({
    productId,
    periodDays
  });
  const pricingMutation = usePricingRecommendation();

  const data = query.data;
  const selectedProduct = data?.selectedProduct ?? null;
  const selectedProductId = selectedProduct?.id ?? null;
  const pricingRecommendation = selectedProductId
    ? (pricingByProduct[selectedProductId] ?? null)
    : null;
  const isGeneratingPricing =
    pricingMutation.isPending &&
    pricingMutation.variables === selectedProductId;
  const hasRecommendation = Boolean(pricingRecommendation);

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

    const normalized =
      typeof value === "string" && !value.includes("T")
        ? `${value}T00:00:00Z`
        : value;
    const parsed = new Date(normalized);

    return Number.isNaN(parsed.getTime()) ? "—" : date.format(parsed);
  };

  const money = (value, currency) => {
    if (value == null) return "—";

    const normalizedCurrency = currency?.toUpperCase() || "JOD";

    if (!moneyFormatters.has(normalizedCurrency)) {
      moneyFormatters.set(
        normalizedCurrency,
        new Intl.NumberFormat(locale, {
          style: "currency",
          currency: normalizedCurrency
        })
      );
    }

    return moneyFormatters.get(normalizedCurrency).format(value);
  };

  const pricingRows = buildPricingRows({
    overviewRows: data?.pricingRecommendations,
    recommendation: pricingRecommendation,
    selectedProduct
  });

  const handleGeneratePricingRecommendation = () => {
    if (!selectedProductId || pricingMutation.isPending) return;

    pricingMutation.mutate(selectedProductId, {
      onSuccess: (recommendation) => {
        setPricingByProduct((current) => ({
          ...current,
          [selectedProductId]: recommendation
        }));
      }
    });
  };

  const handleProductChange = (event) => {
    setProductId(event.target.value);
  };

  const requestExport = async (section) => {
    if (exportInProgress.current || query.isFetching || !data) return;

    exportInProgress.current = true;
    setIsExporting(true);
    setExportNotice(false);

    try {
      const exportData =
        section === "pricing"
          ? { ...data, pricingRecommendations: pricingRows }
          : data;
      const { exportMarketIntelligencePdf } =
        await import("../utils/exportMarketIntelligencePdf.js");

      await exportMarketIntelligencePdf({
        data: exportData,
        section,
        locale,
        periodDays
      });
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

  if (query.isPending) {
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
  }

  if (query.isError) {
    return (
      <EmptyState
        title={t("marketMain.error.title")}
        description={getApiErrorMessage(query.error, t)}
        action={
          <Button size="sm" variant="outline" onClick={() => query.refetch()}>
            {t("marketMain.actions.retry")}
          </Button>
        }
      />
    );
  }

  if (!data?.products?.length) {
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
  }

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
      render: (row) =>
        row.pricingScore == null
          ? "—"
          : `${number.format(row.pricingScore)} / 10`
    },
    {
      key: "compositeScore",
      label: t("marketMain.tables.compositeScore"),
      render: (row) =>
        row.compositeScore == null
          ? "—"
          : `${number.format(row.compositeScore)} / 100`
    },
    {
      key: "relevanceScore",
      label: t("marketMain.tables.relevanceScore"),
      render: (row) =>
        row.relevanceScore == null
          ? "—"
          : `${number.format(row.relevanceScore)} / 100`
    },
    {
      key: "marketPresenceScore",
      label: t("marketMain.tables.presenceScore"),
      render: (row) =>
        row.marketPresenceScore == null
          ? "—"
          : `${number.format(row.marketPresenceScore)} / 100`
    },
    {
      key: "marketPerception",
      label: t("marketMain.tables.perception"),
      render: (row) =>
        row.marketPerception == null ? (
          "—"
        ) : (
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
      render: (row) => money(row.currentPrice, row.currency || currency)
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
      render: (row) => money(row.suggestedPrice, row.currency || currency)
    },
    {
      key: "marketMin",
      label: t("marketMain.tables.marketMin"),
      render: (row) => money(row.marketMin, row.currency || currency)
    },
    {
      key: "marketMax",
      label: t("marketMain.tables.marketMax"),
      render: (row) => money(row.marketMax, row.currency || currency)
    },
    {
      key: "marketAverage",
      label: t("marketMain.tables.marketAverage"),
      render: (row) => money(row.marketAverage, row.currency || currency)
    },
    {
      key: "marketMedian",
      label: t("marketMain.tables.marketMedian"),
      render: (row) => money(row.marketMedian, row.currency || currency)
    },
    {
      key: "matchedCompetitors",
      label: t("marketMain.tables.matchedCompetitors"),
      render: (row) =>
        row.matchedCompetitors == null
          ? "—"
          : number.format(row.matchedCompetitors)
    },
    {
      key: "explanation",
      label: t("marketMain.tables.explanation"),
      className: "market-main-table__explanation",
      render: (row) => localize(row.explanation) || "—"
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

  const pricingMutationFailedForSelectedProduct =
    pricingMutation.isError && pricingMutation.variables === selectedProductId;

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
          onChange={handleProductChange}
          disabled={pricingMutation.isPending}
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
        {data.metrics.map((metric) => (
          <MarketIntelligenceMetricCard
            key={metric.id}
            metric={metric}
            label={t(`marketMain.metrics.${metric.id}`)}
            value={formatMetric(metric)}
          />
        ))}
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
        dataStatus={pricingRows[0]?.dataStatus}
        exportLabel={t("marketMain.actions.exportPdf")}
        exportDisabled={isExporting || query.isFetching}
        onExport={() => requestExport("pricing")}
        actions={
          <Button
            size="sm"
            variant="outline"
            leadingIcon={<RefreshCw size={15} />}
            onClick={handleGeneratePricingRecommendation}
            disabled={!selectedProductId || pricingMutation.isPending}
            aria-busy={isGeneratingPricing || undefined}
          >
            {hasRecommendation
              ? t("marketMain.actions.refreshRecommendation")
              : t("marketMain.actions.generateRecommendation")}
          </Button>
        }
      >
        <MarketIntelligenceTable
          className="is-pricing"
          columns={pricingColumns}
          rows={pricingRows}
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

      {(exportNotice || pricingMutationFailedForSelectedProduct) && (
        <div className="market-main-toast">
          {exportNotice && (
            <Toast
              variant="error"
              message={t("marketMain.export.failed")}
              onClose={() => setExportNotice(false)}
            />
          )}
          {pricingMutationFailedForSelectedProduct && (
            <Toast
              variant="error"
              message={t("marketMain.error.description")}
              onClose={() => pricingMutation.reset()}
            />
          )}
        </div>
      )}
    </div>
  );
}

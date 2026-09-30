import { Document, Page, Text, View } from "@react-pdf/renderer";
import { translate } from "../../../shared/lib/i18n.js";
import { MarketIntelligencePdfHeader } from "./MarketIntelligencePdfHeader.jsx";
import { MarketIntelligencePdfTable } from "./MarketIntelligencePdfTable.jsx";
import { pdfStyles as s } from "./marketIntelligencePdfStyles.js";

const SECTION_KEYS = {
  product_forecasts: "product forecasts",
  pricing: "pricing",
  opportunities: "opportunities",
  "price-changes": "changes"
};

const localize = (value, locale) => {
  if (value && typeof value === "object")
    return value[locale] ?? value.en ?? Object.values(value)[0] ?? "—";
  return value ?? "—";
};

const asDate = (value) => {
  if (!value) return null;
  const result =
    value instanceof Date
      ? value
      : new Date(
          /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value}T00:00:00Z` : value
        );
  return Number.isNaN(result.getTime()) ? null : result;
};

export function ProductsForecastingDocuement({
  data,
  section,
  locale = "en",
  periodDays,
  generatedAt = new Date()
}) {
  const sectionKey = SECTION_KEYS[section];
  if (!sectionKey)
    throw new Error(`Unsupported product forecasting section: ${section}`);

  const rtl = locale === "ar";
  const t = (key, params) => translate(locale, key, params);
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  const currency = data?.selectedProduct?.currency?.toUpperCase() || "JOD";
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC"
  });
  const formatDate = (value) => {
    const parsed = asDate(value);
    return parsed ? dateFormatter.format(parsed) : "—";
  };
  const amount = (value) => {
    if (value == null || !Number.isFinite(Number(value))) return "—";
    try {
      return new Intl.NumberFormat(locale, {
        style: "currency",
        currency
      }).format(Number(value));
    } catch {
      return `${number.format(Number(value))} ${currency}`;
    }
  };
  const score = (value, max) =>
    value == null ? "—" : `${number.format(value)} / ${max}`;
  const status = (row) =>
    row.dataStatus ? t(`dataStatus.${row.dataStatus}.label`) : "—";
  const product = (row) => localize(row.productName, locale);
  const title = t(`marketMain.${sectionKey}.title`);
  const table = (columns, rows, emptyKey, detail) => (
    <MarketIntelligencePdfTable
      columns={columns}
      rows={rows}
      detail={detail}
      emptyLabel={t(`marketMain.empty.${emptyKey}`)}
      rtl={rtl}
    />
  );

  const rowsBySection = {
    competitors: data.competitors || [],
    pricing: data.pricingRecommendations || [],
    opportunities: data.expansionOpportunities || [],
    "price-changes": data.recentPriceChanges || []
  };
  // Each page repeats the report metadata and the table headings. Conservative
  // page sizes leave room for translated headings and multiline values.
  const pageSize = {
    competitors: 7,
    pricing: 4,
    opportunities: 5,
    "price-changes": 7
  }[section];
  const allRows = rowsBySection[section];
  const pages = allRows.length
    ? Array.from({ length: Math.ceil(allRows.length / pageSize) }, (_, index) =>
        allRows.slice(index * pageSize, (index + 1) * pageSize)
      )
    : [[]];

  const renderContent = (pageRows) => {
    let content;
    if (section === "competitors") {
      content = table(
        [
          {
            key: "product",
            label: t("marketMain.tables.product"),
            value: product,
            width: 1.5
          },
          {
            key: "competitor",
            label: t("marketMain.tables.competitor"),
            value: (row) => row.competitorName,
            width: 1.5
          },
          {
            key: "pricing",
            label: t("marketMain.tables.pricingScore"),
            value: (row) => score(row.pricingScore, 10)
          },
          {
            key: "composite",
            label: t("marketMain.tables.compositeScore"),
            value: (row) => score(row.compositeScore, 100)
          },
          {
            key: "relevance",
            label: t("marketMain.tables.relevanceScore"),
            value: (row) => score(row.relevanceScore, 100)
          },
          {
            key: "presence",
            label: t("marketMain.tables.presenceScore"),
            value: (row) => score(row.marketPresenceScore, 100)
          },
          {
            key: "perception",
            label: t("marketMain.tables.perception"),
            value: (row) =>
              row.marketPerception == null
                ? "—"
                : t(`marketMain.sentiments.${row.marketPerception}`)
          }
        ],
        pageRows,
        "competitorsDescription"
      );
    } else if (section === "pricing") {
      content = table(
        [
          {
            key: "product",
            label: t("marketMain.tables.product"),
            value: product,
            width: 1.6
          },
          {
            key: "current",
            label: t("marketMain.tables.currentPrice"),
            value: (row) => amount(row.currentPrice)
          },
          {
            key: "action",
            label: t("marketMain.tables.action"),
            value: (row) =>
              row.action ? t(`marketMain.actions.${row.action}`) : "—"
          },
          {
            key: "suggested",
            label: t("marketMain.tables.suggestedPrice"),
            value: (row) => amount(row.suggestedPrice)
          },
          {
            key: "min",
            label: t("marketMain.tables.marketMin"),
            value: (row) => amount(row.marketMin)
          },
          {
            key: "max",
            label: t("marketMain.tables.marketMax"),
            value: (row) => amount(row.marketMax)
          },
          {
            key: "average",
            label: t("marketMain.tables.marketAverage"),
            value: (row) => amount(row.marketAverage)
          },
          {
            key: "median",
            label: t("marketMain.tables.marketMedian"),
            value: (row) => amount(row.marketMedian)
          },
          {
            key: "matched",
            label: t("marketMain.tables.matchedCompetitors"),
            value: (row) =>
              row.matchedCompetitors == null
                ? "—"
                : number.format(row.matchedCompetitors)
          }
        ],
        pageRows,
        "pricingDescription",
        (row) => (
          <Text style={rtl && { textAlign: "right" }}>
            <Text style={s.detailLabel}>
              {t("marketMain.tables.explanation")}:{" "}
            </Text>
            {localize(row.explanation, locale)} · {status(row)}
          </Text>
        )
      );
    } else if (section === "opportunities") {
      content = pageRows.length ? (
        pageRows.map((row, index) => (
          <View key={row.id ?? index} style={s.opportunity} wrap={false}>
            <View
              style={[
                s.opportunityTop,
                rtl && { flexDirection: "row-reverse" }
              ]}
            >
              <Text style={[s.opportunityName, rtl && { textAlign: "right" }]}>
                {product(row)}
              </Text>
              <Text style={s.opportunityGrowth}>
                {row.growthPercent == null
                  ? "—"
                  : `${row.growthPercent > 0 ? "+" : ""}${number.format(row.growthPercent)}%`}
              </Text>
            </View>
            <Text
              style={[s.opportunityExplanation, rtl && { textAlign: "right" }]}
            >
              {localize(row.explanation, locale)}
            </Text>
            <Text style={[s.status, rtl && { textAlign: "right" }]}>
              {t("marketMain.opportunities.growth")} · {status(row)}
            </Text>
          </View>
        ))
      ) : (
        <Text style={s.empty}>
          {t("marketMain.empty.opportunitiesDescription")}
        </Text>
      );
    } else {
      content = table(
        [
          {
            key: "date",
            label: t("marketMain.tables.date"),
            value: (row) => formatDate(row.date)
          },
          {
            key: "competitor",
            label: t("marketMain.tables.competitor"),
            value: (row) => row.competitor,
            width: 1.5
          },
          {
            key: "product",
            label: t("marketMain.tables.product"),
            value: product,
            width: 1.5
          },
          {
            key: "previous",
            label: t("marketMain.tables.previousPrice"),
            value: (row) => amount(row.previousPrice)
          },
          {
            key: "new",
            label: t("marketMain.tables.newPrice"),
            value: (row) => amount(row.newPrice)
          },
          {
            key: "change",
            label: t("marketMain.tables.change"),
            value: (row) =>
              row.newPrice == null || row.previousPrice == null
                ? "—"
                : `${amount(Math.abs(row.newPrice - row.previousPrice))} ${row.direction ? t(`marketMain.changes.${row.direction}`) : ""}`,
            width: 1.4
          },
          {
            key: "detected",
            label: t("marketMain.tables.detected"),
            value: (row) => formatDate(row.detectedAt)
          }
        ],
        pageRows,
        "changesDescription"
      );
    }
    return content;
  };

  return (
    <Document
      title={`${t("marketMain.page.title")} — ${title}`}
      author="CEOPRO-AI"
    >
      {pages.map((pageRows, pageIndex) => (
        <Page
          key={pageIndex}
          size="A4"
          orientation={section === "opportunities" ? "portrait" : "landscape"}
          style={s.page}
          wrap
        >
          <MarketIntelligencePdfHeader
            title={title}
            subtitle={t(`marketMain.${sectionKey}.subtitle`, {
              product: localize(data.selectedProduct?.name, locale)
            })}
            product={localize(data.selectedProduct?.name, locale)}
            period={t(`market.controls.last${periodDays}`)}
            generated={formatDate(generatedAt)}
            labels={{
              product: t("marketMain.product.label"),
              period: t("marketMain.actions.dateRange"),
              generated: t("marketMain.export.generated")
            }}
            rtl={rtl}
          />
          <Text style={[s.sectionHeading, rtl && { textAlign: "right" }]}>
            {title}
          </Text>
          {renderContent(pageRows)}
          <View style={s.footer} fixed>
            <Text>CEOPRO-AI · {t("marketMain.page.title")}</Text>
            <Text
              render={({ pageNumber, totalPages }) =>
                `${pageNumber} / ${totalPages}`
              }
            />
          </View>
        </Page>
      ))}
    </Document>
  );
}

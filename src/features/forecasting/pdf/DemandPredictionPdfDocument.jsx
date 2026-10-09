import { Document, Page, Text, View } from "@react-pdf/renderer";
import { translate } from "../../../shared/lib/i18n.js";
import {
  forecastFormatters,
  localize,
  asForecastDate
} from "../utils/forecastFormatters.js";
import { DemandPredictionPdfHeader } from "./DemandPredictionPdfHeader.jsx";
import { DemandPredictionPdfTable } from "./DemandPredictionPdfTable.jsx";
import { pdfStyles as s } from "./demandPredictionPdfStyles.js";

export function DemandPredictionPdfDocument({
  data,
  locale = "en",
  generatedAt = new Date()
}) {
  const t = (key, values) => translate(locale, key, values);
  const rtl = locale === "ar";
  const f = forecastFormatters(locale);
  const ltr = (value) => `\u202a${value}\u202c`;

  f.formatDate = (value) => {
    const date = asForecastDate(value);
    return date ? ltr(date.toISOString().slice(0, 10)) : "—";
  };

  f.formatPeriod = (row) => {
    const start = asForecastDate(row.date);
    const end = asForecastDate(row.endDate);
    if (!start || !end) return "—";
    return ltr(
      start.getTime() === end.getTime()
        ? start.toISOString().slice(0, 10)
        : `${start.toISOString().slice(0, 10)} / ${end
            .toISOString()
            .slice(0, 10)}`
    );
  };

  const detail = Boolean(data.product);
  const title = t("demandApproved.page.title");
  const noData = t("demandApproved.common.notAvailable");

  const status = (value, namespace, allowed) =>
    allowed.includes(value)
      ? t(`demandApproved.${namespace}.${value}`)
      : noData;
  const action = (value) =>
    status(value, "recommendations", ["restock", "reduce", "monitor"]);
  const trend = (value) =>
    status(value, "trends", ["increasing", "decreasing", "stable"]);

  const tableSections = [];
  const addTable = (heading, columns, rows) => {
    const chunks = rows?.length
      ? Array.from({ length: Math.ceil(rows.length / 6) }, (_, index) =>
          rows.slice(index * 6, (index + 1) * 6)
        )
      : [[]];
    chunks.forEach((chunk) =>
      tableSections.push({ heading, columns, rows: chunk })
    );
  };

  const metricRows = (data.metrics || []).map((metric) => ({
    id: metric.id,
    label:
      metric.id === "next30Forecast"
        ? t("demandApproved.metrics.selectedForecast", {
            days: data.filters?.periodDays
          })
        : t(
            `demandApproved.${detail ? "detailMetrics" : "metrics"}.${
              metric.id
            }`
          ),
    value:
      metric.format === "date"
        ? f.formatDate(metric.value)
        : f.formatMetric(metric, t("demandApproved.common.units")),
    status: metric.dataStatus
      ? t(`dataStatus.${metric.dataStatus}.label`)
      : noData
  }));

  addTable(
    t("demandApproved.metrics.label"),
    [
      {
        key: "label",
        label: t("demandApproved.pdf.metric"),
        value: (row) => row.label,
        width: 2
      },
      {
        key: "value",
        label: t("demandApproved.pdf.value"),
        value: (row) => row.value
      },
      {
        key: "status",
        label: t("demandApproved.pdf.source"),
        value: (row) => row.status
      }
    ],
    metricRows
  );

  if (!detail) {
    addTable(
      t("demandApproved.forecasts.title"),
      [
        {
          key: "name",
          label: t("demandApproved.table.product"),
          value: (row) => localize(row.name, locale),
          width: 1.6
        },
        {
          key: "stock",
          label: t("demandApproved.table.currentStock"),
          value: (row) => f.formatNumber(row.currentStock)
        },
        {
          key: "demand",
          label: t("demandApproved.table.expectedDemand"),
          value: (row) => f.formatNumber(row.expectedDemand)
        },
        {
          key: "date",
          label: t("demandApproved.table.targetDate"),
          value: (row) => f.formatDate(row.targetDate)
        },
        {
          key: "range",
          label: t("demandApproved.table.confidenceRange"),
          value: (row) => f.formatRange(row.confidenceRange)
        },
        {
          key: "trend",
          label: t("demandApproved.table.trend"),
          value: (row) => trend(row.trend)
        },
        {
          key: "action",
          label: t("demandApproved.table.recommendedAction"),
          value: (row) => action(row.recommendedAction)
        }
      ],
      data.forecasts
    );
  }

  if (detail) {
    addTable(
      t("demandApproved.history.title"),
      [
        {
          key: "period",
          label: t("demandApproved.history.date"),
          value: f.formatPeriod,
          width: 1.6
        },
        {
          key: "demand",
          label: t("demandApproved.history.forecast"),
          value: (row) => f.formatNumber(row.forecastedDemand)
        },
        {
          key: "lower",
          label: t("demandApproved.history.lower"),
          value: (row) => f.formatNumber(row.lowerBound)
        },
        {
          key: "upper",
          label: t("demandApproved.history.upper"),
          value: (row) => f.formatNumber(row.upperBound)
        },
        {
          key: "actual",
          label: t("demandApproved.history.actual"),
          value: (row) => f.formatNumber(row.actualDemand)
        }
      ],
      data.forecastHistory
    );

    const rec = data.recommendation;
    addTable(
      t("demandApproved.recommendation.title"),
      [
        {
          key: "action",
          label: t("demandApproved.table.recommendedAction"),
          value: (row) => action(row.action)
        },
        {
          key: "quantity",
          label: t("demandApproved.recommendation.quantity"),
          value: (row) => f.formatNumber(row.suggestedQuantity)
        },
        {
          key: "period",
          label: t("demandApproved.history.date"),
          value: (row) =>
            f.formatPeriod({
              date: row.startDate,
              endDate: row.targetDate
            }),
          width: 2
        }
      ],
      rec ? [rec] : []
    );
  }

  const points = detail ? data.chart?.points : data.totalForecast?.points;
  const chartRows = (points ?? [])
    .filter((row) =>
      detail
        ? row.actual != null || row.forecast != null
        : row.value != null
    )
    .map((row) => ({ ...row, id: row.date }));

  addTable(
    t(
      detail
        ? "demandApproved.detail.chartTitle"
        : "demandApproved.chart.totalTitle"
    ),
    [
      {
        key: "date",
        label: t("demandApproved.history.date"),
        value: (row) => f.formatDate(row.date)
      },
      ...(detail
        ? [
            {
              key: "actual",
              label: t("demandApproved.chart.actual"),
              value: (row) => f.formatNumber(row.actual)
            }
          ]
        : []),
      {
        key: "forecast",
        label: t("demandApproved.chart.forecast"),
        value: (row) =>
          f.formatNumber(detail ? row.forecast : row.value)
      },
      ...(detail
        ? [
            {
              key: "lower",
              label: t("demandApproved.history.lower"),
              value: (row) => f.formatNumber(row.lower)
            },
            {
              key: "upper",
              label: t("demandApproved.history.upper"),
              value: (row) => f.formatNumber(row.upper)
            }
          ]
        : [])
    ],
    chartRows
  );

  const generated = asForecastDate(generatedAt);
  const generatedLabel = generated
    ? ltr(
        `${generated.toISOString().slice(0, 16).replace("T", " ")} UTC`
      )
    : "—";

  const product = detail
    ? localize(data.product.name, locale)
    : data.filters?.productId === "all"
      ? t("demandApproved.filters.allProducts")
      : localize(
          data.products?.find(
            (item) => item.id === data.filters?.productId
          )?.name,
          locale
        );

  return (
    <Document title={title} author="KEEL">
      {tableSections.map((section, index) => (
        <Page
          key={index}
          size="A4"
          orientation="landscape"
          style={s.page}
          wrap
        >
          <DemandPredictionPdfHeader
            title={title}
            subtitle={section.heading}
            product={product}
            period={f.formatPeriod({
              date: data.filters?.startDate,
              endDate: data.filters?.endDate
            })}
            generated={generatedLabel}
            rtl={rtl}
            labels={{
              product: t("demandApproved.filters.product"),
              period: t("demandApproved.filters.period"),
              generated: t("demandApproved.pdf.generated")
            }}
          />

          <Text
            style={[
              s.sectionHeading,
              rtl && { textAlign: "right" }
            ]}
          >
            {section.heading}
          </Text>

          <DemandPredictionPdfTable
            columns={section.columns}
            rows={section.rows}
            emptyLabel={noData}
            rtl={rtl}
          />

          <View style={s.footer} fixed>
            <Text>KEEL · {title}</Text>
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

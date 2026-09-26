import { Download } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Badge from "../../../shared/components/ui/Badge.jsx";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { MarketMetricCard } from "../components/MarketMetricCard.jsx";
import {
  MarketTrendChart,
  SeasonalBarChart
} from "../components/MarketTrendChart.jsx";
import { MarketDriverList } from "../components/MarketDriverList.jsx";
import { MarketSignalsTable } from "../components/MarketSignalsTable.jsx";
import { ComingSoonPanel } from "../../../shared/components/ui/ComingSoonPanel.jsx";
import {
  industryMetrics,
  priceTrendSeries,
  seasonalSeries,
  positiveDrivers,
  negativeDrivers,
  categoryActivity,
  emergingTrends,
  marketSignals
} from "../config/marketPreviewData.js";
import "../styles/MarketIntelligence.css";

export function IndustryMarketTrendsPage() {
  const { t } = useI18n();
  return (
    <DashboardLayout>
      <div className="market-page">
        <PageHeader
          title={t("market.industry.title", "Industry Trends")}
          subtitle={t(
            "market.industry.subtitle",
            "Macro-level market movements"
          )}
          actions={
            <>
              <select
                className="market-filter-select"
                aria-label={t("market.controls.industry")}
                defaultValue="home"
              >
                <option value="home">
                  {t("market.controls.homeInternet")}
                </option>
              </select>
              <select
                className="market-filter-select"
                aria-label={t("market.controls.timePeriod")}
                defaultValue="12"
              >
                <option value="12">{t("market.controls.last12")}</option>
              </select>
              <Button
                variant="outline"
                size="sm"
                leadingIcon={<Download size={15} />}
              >
                {t("market.controls.export")}
              </Button>
            </>
          }
        />
        <MarketTabs />

        {/* COMING SOON OVERLAY WRAPPER */}
        <div
          style={{
            position: "relative",
            minHeight: "800px",
            marginTop: "1.5rem"
          }}
        >
          <div
            style={{
              position: "absolute",
              inset: 0,
              zIndex: 50,
              backgroundColor: "rgba(255, 255, 255, 0.3)",
              backdropFilter: "blur(6px)",
              WebkitBackdropFilter: "blur(6px)",
              display: "flex",
              alignItems: "flex-start",
              justifyContent: "center",
              paddingTop: "15vh",
              borderRadius: "12px"
            }}
          >
            <div
              style={{
                background: "var(--bg-primary, #ffffff)",
                borderRadius: "12px",
                boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.25)",
                maxWidth: "600px",
                width: "90%"
              }}
            >
              <ComingSoonPanel
                t={t}
                title={t("market.industry.title", "Industry Trends")}
                subtitle={t(
                  "market.industry.subtitle",
                  "Macro-level market movements"
                )}
              />
            </div>
          </div>

          {/* UN-CLICKABLE PREVIEW UI */}
          <div
            style={{
              pointerEvents: "none",
              userSelect: "none",
              opacity: 0.6,
              filter: "grayscale(30%)"
            }}
          >
            <section className="market-section">
              <div className="market-metric-grid">
                {industryMetrics.map((item) => (
                  <MarketMetricCard key={item.id} item={item} t={t} />
                ))}
              </div>
            </section>

            <section className="market-grid market-grid--trend">
              <Card className="market-panel market-trend-panel">
                <div className="market-panel__header">
                  <div>
                    <h2>{t("market.industry.priceTitle")}</h2>
                    <p>{t("market.industry.priceSubtitle")}</p>
                  </div>
                </div>
                <MarketTrendChart
                  current={priceTrendSeries.current}
                  previous={priceTrendSeries.previous}
                  labels={[
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec"
                  ]}
                  ariaLabel={t("market.industry.priceChartLabel")}
                />
              </Card>
              <div className="market-industry-side">
                <Card className="market-panel market-sentiment-panel">
                  <div className="market-panel__header">
                    <h2>{t("market.metrics.sentiment")}</h2>
                    <Badge variant="light-success">↑ +4.2% YTD</Badge>
                  </div>
                  <strong>{t("market.industry.bullish")}</strong>
                  <div className="market-progress market-progress--large">
                    <b style={{ width: "75%" }} />
                  </div>
                  <span>75% {t("market.industry.positiveIndicators")}</span>
                </Card>
                <Card className="market-panel market-key-drivers">
                  <div className="market-panel__header">
                    <h2>{t("market.industry.keyDrivers")}</h2>
                  </div>
                  <MarketDriverList
                    t={t}
                    positive={positiveDrivers.slice(0, 3)}
                    negative={negativeDrivers.slice(0, 2)}
                  />
                </Card>
              </div>
            </section>

            <section className="market-section market-panel">
              <div className="market-panel__header">
                <div>
                  <h2>{t("market.industry.seasonalTitle")}</h2>
                  <p>{t("market.industry.seasonalSubtitle")}</p>
                </div>
              </div>
              <SeasonalBarChart
                historical={seasonalSeries.historical}
                current={seasonalSeries.current}
                labels={["Q1", "Q2", "Q3", "Q4"]}
                ariaLabel={t("market.industry.seasonalChartLabel")}
              />
            </section>

            <section className="market-grid market-grid--two market-section">
              <Card className="market-panel">
                <div className="market-panel__header">
                  <div>
                    <h2>{t("market.industry.categoryTitle")}</h2>
                    <p>{t("market.industry.categorySubtitle")}</p>
                  </div>
                </div>
                <div className="market-category-list">
                  {categoryActivity.map((item) => (
                    <div key={item.labelKey}>
                      <span>{t(item.labelKey)}</span>
                      <i>
                        <b style={{ width: `${item.value}%` }} />
                      </i>
                      <strong>{item.value}%</strong>
                    </div>
                  ))}
                </div>
              </Card>
              <Card className="market-panel">
                <div className="market-panel__header">
                  <div>
                    <h2>{t("market.industry.emergingTitle")}</h2>
                  </div>
                </div>
                <div className="market-emerging-list">
                  {emergingTrends.map((item) => (
                    <div key={item.rank}>
                      <b>{item.rank}</b>
                      <span>
                        <strong>{t(item.titleKey)}</strong>
                        <small>{t(item.descriptionKey)}</small>
                      </span>
                      <Badge
                        variant={
                          item.impactKey.includes("high")
                            ? "light-success"
                            : "warning"
                        }
                      >
                        {t(item.impactKey)}
                      </Badge>
                    </div>
                  ))}
                </div>
              </Card>
            </section>

            <section className="market-section market-panel">
              <div className="market-panel__header">
                <div>
                  <h2>{t("market.industry.signalsTitle")}</h2>
                  <p>{t("market.industry.signalsSubtitle")}</p>
                </div>
              </div>
              <MarketSignalsTable t={t} rows={marketSignals} />
            </section>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Download, Search, TrendingDown, TrendingUp } from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Badge from "../../../shared/components/ui/Badge.jsx";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { ComingSoonPanel } from "../../../shared/components/ui/ComingSoonPanel.jsx";
import { leaderboard } from "../config/finalPreviewData.js";
import "../styles/MarketIntelligence.css";

export function MarketLeaderboardPage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const [sort, setSort] = useState("score");
  const [query, setQuery] = useState("");

  const rows = useMemo(
    () =>
      [...leaderboard]
        .filter((row) => row.name.toLowerCase().includes(query.toLowerCase()))
        .sort((a, b) => b[sort] - a[sort]),
    [sort, query]
  );

  const summary = [
    ["market.reference.totalCompetitors", "24", "+3"],
    ["market.reference.averageScore", "68.4 / 100", "+5.2"],
    ["market.reference.highestPrice", "92.1 / 100", "Stratos Analytics"],
    ["market.reference.topSentiment", "88.3 / 100", "Nova Insights"]
  ];

  const methods = [
    [
      "marketScoped.leaderboard.priceMethod",
      "marketScoped.leaderboard.priceMethodText"
    ],
    [
      "marketScoped.leaderboard.sentimentMethod",
      "marketScoped.leaderboard.sentimentMethodText"
    ],
    [
      "marketScoped.leaderboard.activityMethod",
      "marketScoped.leaderboard.activityMethodText"
    ],
    [
      "marketScoped.leaderboard.varietyMethod",
      "marketScoped.leaderboard.varietyMethodText"
    ],
    [
      "marketScoped.leaderboard.growthMethod",
      "marketScoped.leaderboard.growthMethodText"
    ]
  ];

  return (
    <DashboardLayout>
      <div className="market-page leaderboard-reference-page">
        <PageHeader
          title={t("market.final.leaderboardTitle")}
          subtitle={t("market.reference.leaderboardSubtitle")}
          actions={
            <Button variant="secondary" leadingIcon={<Download size={15} />}>
              {t("marketScoped.leaderboard.export")}
            </Button>
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
                title={t("market.final.leaderboardTitle", "Leaderboard")}
                subtitle={t(
                  "market.reference.leaderboardSubtitle",
                  "Market rankings and performance"
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
            <section className="reference-kpi-grid">
              {summary.map(([label, value, trend]) => (
                <Card className="reference-kpi" key={label}>
                  <small>{t(label)}</small>
                  <strong>{value}</strong>
                  <span>{trend}</span>
                </Card>
              ))}
            </section>

            <div className="leaderboard-filter-row">
              <select aria-label={t("marketScoped.leaderboard.industry")}>
                <option>{t("marketScoped.leaderboard.homeInternet")}</option>
              </select>
              <select aria-label={t("marketScoped.leaderboard.period")}>
                <option>{t("marketScoped.leaderboard.quarter")}</option>
              </select>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value)}
                aria-label={t("marketScoped.leaderboard.sort")}
              >
                <option value="score">
                  {t("marketScoped.leaderboard.compositeScore")}
                </option>
                <option value="price">
                  {t("marketScoped.leaderboard.priceScore")}
                </option>
                <option value="sentiment">
                  {t("marketScoped.leaderboard.sentimentScore")}
                </option>
              </select>
              <select aria-label={t("marketScoped.leaderboard.view")}>
                <option>{t("marketScoped.leaderboard.top10")}</option>
              </select>
              <label>
                <Search size={15} />
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder={t("marketScoped.leaderboard.search")}
                  aria-label={t("marketScoped.leaderboard.search")}
                />
              </label>
            </div>

            <section className="market-panel leaderboard-table-panel">
              <div className="market-table-wrap">
                <table className="market-table">
                  <thead>
                    <tr>
                      <th>{t("marketScoped.leaderboard.competitor")}</th>
                      <th>{t("marketScoped.leaderboard.priceScore")}</th>
                      <th>{t("marketScoped.leaderboard.sentimentScore")}</th>
                      <th>{t("marketScoped.leaderboard.activityScore")}</th>
                      <th>{t("marketScoped.leaderboard.compositeScore")}</th>
                      <th>{t("marketScoped.leaderboard.trend")}</th>
                      <th>{t("marketScoped.common.actions")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) => (
                      <tr key={row.id}>
                        <td>
                          <span className="market-entity-logo">
                            {row.name.charAt(0)}
                          </span>
                          <strong>{row.name}</strong>
                          <small>{row.domain}</small>
                        </td>
                        <td>
                          <Badge
                            variant={
                              row.price > 70
                                ? "light-success"
                                : row.price < 60
                                  ? "error"
                                  : "warning"
                            }
                          >
                            {row.price}/100
                          </Badge>
                        </td>
                        <td>
                          <Badge
                            variant={
                              row.sentiment > 70
                                ? "light-success"
                                : row.sentiment < 60
                                  ? "error"
                                  : "warning"
                            }
                          >
                            {row.sentiment}/100
                          </Badge>
                        </td>
                        <td>
                          <Badge
                            variant={
                              row.activity > 70
                                ? "light-success"
                                : row.activity < 60
                                  ? "error"
                                  : "warning"
                            }
                          >
                            {row.activity}/100
                          </Badge>
                        </td>
                        <td>
                          <span className="leaderboard-score">
                            <strong>{row.score}</strong>
                            <i>
                              <b style={{ width: row.score + "%" }} />
                            </i>
                          </span>
                        </td>
                        <td
                          className={
                            row.movement < 0
                              ? "negative-number"
                              : "positive-number"
                          }
                        >
                          {row.movement > 0
                            ? "+ " + row.movement
                            : row.movement < 0
                              ? "- " + Math.abs(row.movement)
                              : "--"}
                        </td>
                        <td>
                          <button
                            className="market-table-action"
                            onClick={() =>
                              navigate("/market/competitors/" + row.id)
                            }
                          >
                            {t("marketScoped.common.viewDetails")}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="reference-pagination">
                {t("marketScoped.leaderboard.showing")}
                <span>
                  <button>{t("marketScoped.leaderboard.previous")}</button>
                  <button className="active">1</button>
                  <button>2</button>
                  <button>3</button>
                  <button>{t("marketScoped.leaderboard.next")}</button>
                </span>
              </div>
            </section>

            <section className="leaderboard-lower-grid">
              <Card className="market-panel">
                <h2>{t("market.reference.scoreBreakdown")}</h2>
                <div
                  className="score-breakdown"
                  role="img"
                  aria-label={t("market.reference.scoreBreakdown")}
                >
                  {leaderboard.slice(0, 5).map((row) => (
                    <div key={row.id}>
                      <div>
                        <i style={{ height: row.price + "px" }} />
                        <i style={{ height: row.sentiment + "px" }} />
                        <i style={{ height: row.activity + "px" }} />
                      </div>
                      <small>{row.name.split(" ")[0]}</small>
                    </div>
                  ))}
                </div>
              </Card>
              <Card className="market-panel methodology">
                <h2>{t("market.reference.methodology")}</h2>
                <p>{t("market.reference.methodologyText")}</p>
                {methods.map(([titleKey, copyKey]) => (
                  <div key={titleKey}>
                    <strong>{t(titleKey)}</strong>
                    <small>{t(copyKey)}</small>
                  </div>
                ))}
              </Card>
            </section>

            <section className="leaderboard-lower-grid">
              <Card className="market-panel">
                <div className="market-panel__header">
                  <h2>{t("market.reference.keyInsightsTitle")}</h2>
                  <button className="market-link">
                    {t("marketScoped.leaderboard.viewAll")}
                  </button>
                </div>
                <div className="leaderboard-insights">
                  <p>
                    <TrendingUp size={16} />
                    {t("marketScoped.leaderboard.insight1")}
                  </p>
                  <p>{t("marketScoped.leaderboard.insight2")}</p>
                  <p>
                    <TrendingDown size={16} />
                    {t("marketScoped.leaderboard.insight3")}
                  </p>
                </div>
              </Card>
              <Card className="market-panel">
                <h2>{t("market.reference.topMovers")}</h2>
                <div className="movers-grid">
                  <div>
                    <strong>{t("market.reference.biggestImprovers")}</strong>
                    <p>
                      {t("marketScoped.leaderboard.orange")} <b>+3 / +12.5</b>
                    </p>
                    <p>
                      {t("marketScoped.leaderboard.fibernet")} <b>+2 / +8.3</b>
                    </p>
                    <p>
                      {t("marketScoped.leaderboard.speedConnect")}{" "}
                      <b>+2 / +7.1</b>
                    </p>
                  </div>
                  <div>
                    <strong>{t("market.reference.biggestDecliners")}</strong>
                    <p>
                      {t("marketScoped.leaderboard.novaQuery")} <b>-1 / -6.2</b>
                    </p>
                    <p>
                      {t("marketScoped.leaderboard.linkPlus")} <b>-1 / -5.1</b>
                    </p>
                    <p>
                      {t("marketScoped.leaderboard.umniah")} <b>-2 / -4.8</b>
                    </p>
                  </div>
                </div>
              </Card>
            </section>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  BarChart3,
  Download,
  Lightbulb,
  Search,
  Sparkles,
  TrendingUp,
  Wifi
} from "lucide-react";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Button from "../../../shared/components/ui/Button.jsx";
import Badge from "../../../shared/components/ui/Badge.jsx";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { ComingSoonPanel } from "../../../shared/components/ui/ComingSoonPanel.jsx";
import {
  opportunities,
  opportunitySummary
} from "../config/finalPreviewData.js";
import "../styles/MarketIntelligence.css";

const OpportunityCard = ({ item, t }) => (
  <Card className="reference-opportunity-card">
    <div className="opportunity-card-heading">
      <span>
        <Wifi size={20} />
      </span>
      <strong>{t(item.shortTitleKey)}</strong>
      <Badge
        variant={
          item.potentialKey.endsWith("high") ? "light-success" : "warning"
        }
      >
        {t(item.potentialKey)}
      </Badge>
    </div>
    <p>{t(item.descriptionKey)}</p>
    <dl>
      <div>
        <dt>{t("marketScoped.opportunities.marketSizeShort")}</dt>
        <dd>{item.marketSize}</dd>
      </div>
      <div>
        <dt>{t("marketScoped.opportunities.demandGrowth")}</dt>
        <dd>{item.growth}</dd>
      </div>
      <div>
        <dt>{t("marketScoped.opportunities.competition")}</dt>
        <dd>{t(item.competitionKey)}</dd>
      </div>
    </dl>
    <button type="button">{t("marketScoped.common.viewDetails")} →</button>
  </Card>
);

export function MarketOpportunitiesPage() {
  const { t } = useI18n();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [potential, setPotential] = useState("all");

  const filtered = useMemo(
    () =>
      opportunities.filter(
        (item) =>
          (category === "all" || item.categoryKey === category) &&
          (potential === "all" || item.potentialKey === potential) &&
          t(item.titleKey).toLowerCase().includes(query.toLowerCase())
      ),
    [category, potential, query, t]
  );

  return (
    <DashboardLayout>
      <div className="market-page opportunities-reference-page">
        <PageHeader
          title={t(
            "market.final.opportunitiesTitle",
            "Expansion Opportunities"
          )}
          subtitle={t(
            "market.reference.opportunitiesSubtitle",
            "Automated market gap detection"
          )}
          actions={
            <Button variant="secondary" leadingIcon={<Download size={15} />}>
              {t("market.reference.exportReport")}
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
                title={t(
                  "market.final.opportunitiesTitle",
                  "Expansion Opportunities"
                )}
                subtitle={t(
                  "market.reference.opportunitiesSubtitle",
                  "Automated market gap detection"
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
              {opportunitySummary.map((item) => (
                <Card className="reference-kpi" key={item.id}>
                  <small>{t(item.labelKey)}</small>
                  <strong>{item.value}</strong>
                  <span>
                    +{item.trend} {t("marketScoped.common.lastPeriod")}
                  </span>
                </Card>
              ))}
            </section>

            <Card className="opportunity-ai-insight">
              <span>
                <Sparkles size={19} />
              </span>
              <div>
                <h2>{t("marketScoped.opportunities.aiTitle")}</h2>
                <p>{t("marketScoped.opportunities.aiText")}</p>
              </div>
              <Button variant="secondary">
                {t("marketScoped.opportunities.fullAnalysis")} →
              </Button>
            </Card>

            <div className="opportunity-filter-row">
              <select aria-label="Industry">
                <option>{t("marketScoped.common.all")}</option>
              </select>
              <select aria-label="Type">
                <option>{t("marketScoped.common.all")}</option>
              </select>
              <select aria-label="Potential">
                <option>{t("marketScoped.common.all")}</option>
              </select>
              <label>
                <Search size={15} />
                <input placeholder={t("marketScoped.opportunities.search")} />
              </label>
            </div>

            <section className="market-panel">
              <div className="market-panel__header">
                <div>
                  <h2>{t("market.reference.topOpportunities")}</h2>
                  <p>{t("marketScoped.opportunities.topSubtitle")}</p>
                </div>
              </div>
              <div className="reference-top-opportunities">
                {filtered.slice(0, 3).map((item) => (
                  <OpportunityCard key={item.id} item={item} t={t} />
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

export function OpportunityDetailPage() {
  return <MarketOpportunitiesPage />;
}

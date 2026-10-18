import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import PageHeader from "../../../shared/components/layout/PageHeader.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { MarketTabs } from "../components/MarketTabs.jsx";
import { ComingSoonPanel } from "../../../shared/components/ui/ComingSoonPanel.jsx";

export function MarketIntelligenceReportsPage() {
  const { t } = useI18n();

  return (
    <DashboardLayout>
      <div className="market-page">
        <PageHeader
          title={t("market.reports.title", "Intelligence Reports")}
          subtitle={t(
            "market.reports.subtitle",
            "Automated executive summaries"
          )}
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
                title={t("market.reports.title", "Intelligence Reports")}
                subtitle={t(
                  "market.reports.subtitle",
                  "Automated PDF and Excel generation"
                )}
              />
            </div>
          </div>

          {/* UN-CLICKABLE PREVIEW UI (Skeletal Layout for empty page) */}
          <div
            style={{
              pointerEvents: "none",
              userSelect: "none",
              opacity: 0.6,
              filter: "grayscale(30%)",
              display: "grid",
              gap: "1.5rem"
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(3, 1fr)",
                gap: "1.5rem"
              }}
            >
              {[1, 2, 3].map((i) => (
                <Card key={i} style={{ padding: "1.5rem" }}>
                  <Skeleton
                    height="20px"
                    width="60%"
                    style={{ marginBottom: "1rem" }}
                  />
                  <Skeleton
                    height="10px"
                    width="100%"
                    style={{ marginBottom: "0.5rem" }}
                  />
                  <Skeleton height="10px" width="80%" />
                </Card>
              ))}
            </div>
            <Card style={{ padding: "1.5rem" }}>
              <Skeleton
                height="30px"
                width="200px"
                style={{ marginBottom: "2rem" }}
              />
              <Skeleton height="300px" width="100%" variant="rectangular" />
            </Card>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}

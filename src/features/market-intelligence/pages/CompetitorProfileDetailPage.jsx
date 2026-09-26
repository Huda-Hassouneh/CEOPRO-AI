import { useNavigate, useParams } from "react-router-dom";
import { useI18n } from "../../../app/providers/I18nProvider.jsx";
import { DashboardLayout } from "../../../app/layouts/DashboardLayout.jsx";
import Card from "../../../shared/components/ui/Card.jsx";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import EmptyState from "../../../shared/components/ui/EmptyState.jsx";
import { CompetitorDetailHeader } from "../components/CompetitorDetailSections.jsx";
import { useCompetitorProfile } from "../hooks/useCompetitorProfile.js";
import "../styles/MarketIntelligence.css";

export function CompetitorProfileDetailPage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const { competitorId } = useParams();

  const {
    data: detail,
    isLoading,
    isError
  } = useCompetitorProfile(competitorId);

  const formatDate = (dateString) => {
    return new Intl.DateTimeFormat(locale, {
      month: "short",
      day: "numeric",
      year: "numeric"
    }).format(new Date(dateString));
  };

  const getLocalizedName = (nameObj) =>
    nameObj?.[locale] || nameObj?.en || "Unknown";

  if (isLoading) {
    return (
      <DashboardLayout>
        <div className="market-page competitor-detail-page">
          <Skeleton height="150px" variant="rectangular" />
          <Skeleton
            height="300px"
            variant="rectangular"
            style={{ marginTop: "1rem" }}
          />
        </div>
      </DashboardLayout>
    );
  }

  if (isError || !detail) {
    return (
      <DashboardLayout>
        <EmptyState
          title="Competitor Not Found"
          description="This competitor could not be loaded or is not tracked."
          action={
            <button onClick={() => navigate("/market/competitors")}>
              Go Back
            </button>
          }
        />
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="market-page competitor-detail-page">
        <CompetitorDetailHeader
          t={t}
          detail={detail}
          onBack={() => navigate("/market/competitors")}
        />

        <section
          className="market-panel competitor-products"
          style={{ marginTop: "2rem" }}
        >
          <div className="market-panel__header">
            <div>
              <h2>{t("market.detail.productsTitle", "Mapped Products")}</h2>
              <p>
                {t(
                  "market.detail.productsSubtitle",
                  "Your products tracked against this competitor"
                )}
              </p>
            </div>
          </div>

          <div className="market-table-wrap">
            <table className="market-table">
              <thead>
                <tr>
                  <th>{t("market.detail.productName", "Product")}</th>
                  <th>{t("market.detail.ourPrice", "Our Price")}</th>
                  <th>
                    {t("market.detail.competitorPrice", "Competitor Price")}
                  </th>
                  <th>{t("market.detail.lastUpdated", "Last Checked")}</th>
                </tr>
              </thead>
              <tbody>
                {detail.mappedProducts.length === 0 ? (
                  <tr>
                    <td
                      colSpan="4"
                      style={{ textAlign: "center", padding: "2rem" }}
                    >
                      No products mapped to this competitor yet.
                    </td>
                  </tr>
                ) : (
                  detail.mappedProducts.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{getLocalizedName(item.name)}</strong>
                      </td>
                      <td>
                        {item.ourPrice} {item.currency}
                      </td>
                      <td>
                        {item.competitorPrice} {item.currency}
                      </td>
                      <td>{formatDate(item.lastUpdated)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <section
          className="market-grid market-grid--two"
          style={{ marginTop: "2rem" }}
        >
          <Card className="market-panel" style={{ gridColumn: "1 / -1" }}>
            <div className="market-panel__header">
              <h2>
                {t("market.detail.recentActivity", "Recent Price Changes")}
              </h2>
            </div>
            <div className="strategic-moves">
              {detail.activity.length === 0 ? (
                <p style={{ padding: "1rem 0" }}>
                  No historical price changes detected.
                </p>
              ) : (
                detail.activity.map((item) => (
                  <div
                    key={item.id}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "1rem",
                      padding: "1rem 0",
                      borderBottom: "1px solid var(--border-color)"
                    }}
                  >
                    <span
                      style={{
                        color:
                          item.newPrice > item.previousPrice ? "red" : "green"
                      }}
                    >
                      ●
                    </span>
                    <strong style={{ flex: 1 }}>
                      {getLocalizedName(item.productName)}
                      <small
                        style={{
                          display: "block",
                          fontWeight: "normal",
                          color: "var(--text-muted)"
                        }}
                      >
                        Price changed from {item.previousPrice} to{" "}
                        {item.newPrice} {item.currency}
                      </small>
                    </strong>
                    <small>{formatDate(item.date)}</small>
                  </div>
                ))
              )}
            </div>
          </Card>
        </section>
      </div>
    </DashboardLayout>
  );
}

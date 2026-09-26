import { useCompetitorLeaderboard } from "../hooks/useCompetitorLeaderboard.js";
import Skeleton from "../../../shared/components/ui/Skeleton.jsx";
import { ExternalLink } from "lucide-react";

export function LeaderboardTable({ t }) {
  const { data: leaderboard, isLoading, isError } = useCompetitorLeaderboard();

  if (isLoading) return <Skeleton height="300px" variant="rectangular" />;
  if (isError)
    return (
      <div style={{ padding: "2rem", color: "red" }}>
        Failed to load leaderboard.
      </div>
    );
  if (!leaderboard || leaderboard.length === 0)
    return <div style={{ padding: "2rem" }}>No tracked competitors found.</div>;

  return (
    <div className="market-table-wrap">
      <table className="market-table">
        <thead>
          <tr>
            <th>{t("market.leaderboard.rank", "Rank")}</th>
            <th>{t("market.competitors.name", "Competitor")}</th>
            <th>
              {t("market.leaderboard.mappedProducts", "Tracked Products")}
            </th>
            <th>
              {t(
                "market.leaderboard.priceIndex",
                "Price Index (vs Our Prices)"
              )}
            </th>
          </tr>
        </thead>
        <tbody>
          {leaderboard.map((row) => (
            <tr key={row.id}>
              <td>
                <strong>#{row.rank}</strong>
              </td>
              <td>
                <div
                  style={{ display: "flex", alignItems: "center", gap: "10px" }}
                >
                  <span
                    className="competitor-logo"
                    style={{ background: "var(--primary-color)" }}
                  >
                    {row.name ? row.name.charAt(0).toUpperCase() : "?"}
                  </span>
                  <div>
                    <strong style={{ display: "block" }}>{row.name}</strong>
                    {row.domain !== "N/A" && (
                      <a
                        href={`https://${row.domain}`}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                          fontSize: "0.85em",
                          display: "flex",
                          alignItems: "center",
                          gap: "4px",
                          color: "var(--text-muted)",
                          textDecoration: "none"
                        }}
                      >
                        {row.domain} <ExternalLink size={12} />
                      </a>
                    )}
                  </div>
                </div>
              </td>
              <td>{row.mappedProductsCount}</td>
              <td>
                {row.priceScore > 0 ? (
                  `${row.priceScore.toFixed(1)}%`
                ) : (
                  <span style={{ color: "var(--text-muted)" }}>
                    No Price Data
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

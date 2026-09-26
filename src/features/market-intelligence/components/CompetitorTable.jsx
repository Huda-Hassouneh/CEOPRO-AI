import { MoreVertical } from "lucide-react";

export function CompetitorTable({ t, rows, onDetails }) {
  if (!rows || rows.length === 0) {
    return (
      <div
        style={{
          padding: "3rem",
          textAlign: "center",
          color: "var(--text-muted)"
        }}
      >
        {t("marketMain.empty.competitorsTitle", "No competitors found.")}
      </div>
    );
  }

  return (
    <div className="competitor-table-wrap">
      <table className="market-table competitor-table">
        <thead>
          <tr>
            <th>{t("market.competitors.name")}</th>
            <th>{t("market.controls.industry")}</th>
            {/* Sentiment, Price, and Activity columns removed: Not supported by DB */}
            <th>{t("market.competitors.updated", "Added Date")}</th>
            <th>{t("market.competitors.actions")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <span
                  className="market-entity-logo"
                  style={{ background: "var(--primary-color, #4f46e5)" }} // Fallback since DB doesn't store hex colors
                >
                  {row.name ? row.name.charAt(0).toUpperCase() : "?"}
                </span>
                <strong>{row.name}</strong>
                {row.website && (
                  <small>{row.website.replace(/^https?:\/\//, "")}</small>
                )}
              </td>

              <td>{row.industry || "—"}</td>

              <td>
                {row.addedAt ? new Date(row.addedAt).toLocaleDateString() : "—"}
              </td>

              <td>
                <button
                  className="market-table-action"
                  type="button"
                  onClick={() => onDetails(row.id)}
                >
                  {t("market.competitors.viewDetails")}
                </button>
                <button
                  className="market-icon-action"
                  type="button"
                  aria-label={t("market.competitors.actions")}
                >
                  <MoreVertical size={15} />
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

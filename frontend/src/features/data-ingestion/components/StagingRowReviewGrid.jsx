import { rowValidationMessage, dataConnectionErrorMessage } from '../../data-connections/utils/connectionPresentation.js';
import { useState } from "react";

export function StagingRowReviewGrid({ rows = [], t, onSave }) {
  const [editingId, setEditingId] = useState(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");
  if (!rows.length) {
    return <p className="staging-row-review-grid__empty">{t("connectData.job.noRows")}</p>;
  }
  return (
    <div className="staging-row-review-grid">
      <table className="connect-data-table">
        <thead><tr><th>{t("connectData.job.row")}</th><th>{t("connectData.job.rowStatus")}</th><th>{t("connectData.job.rowData")}</th><th>{t("connectData.job.rowErrors")}</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{row.id}</td>
              <td>{t(`connectData.job.rowStatuses.${['pending', 'partial', 'invalid', 'committed', 'quarantined', 'valid'].includes(row.status) ? row.status : 'unknown'}`)}</td>
              <td>
                {editingId === row.id ? (
                  <div className="staging-row-review-grid__editor">
                    <textarea
                      rows={8}
                      value={draft}
                      onChange={(event) => setDraft(event.target.value)}
                      aria-label={t("connectData.job.editRowData")}
                    />
                    {error && <small role="alert">{error.key ? t(error.key) : dataConnectionErrorMessage(error.cause, t)}</small>}
                    <button
                      type="button"
                      onClick={async () => {
                        try {
                          const payload = JSON.parse(draft);
                          if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
                            setError({ key: "connectData.job.rowMustBeObject" });
                            return;
                          }
                          await onSave?.(row, payload);
                          setEditingId(null);
                          setError("");
                        } catch (saveError) {
                          setError(saveError instanceof SyntaxError ? { key: "connectData.job.invalidJson" } : { cause: saveError });
                        }
                      }}
                    >
                      {t("connectData.job.saveCorrection")}
                    </button>
                    <button type="button" onClick={() => setEditingId(null)}>
                      {t("common.cancel")}
                    </button>
                  </div>
                ) : (
                  <>
                    <pre>{JSON.stringify(row.payload, null, 2)}</pre>
                    {["invalid", "partial"].includes(row.status) && (
                      <button
                        type="button"
                        onClick={() => {
                          setDraft(JSON.stringify(row.payload, null, 2));
                          setEditingId(row.id);
                          setError("");
                        }}
                      >
                        {t("connectData.job.correctRow")}
                      </button>
                    )}
                  </>
                )}
              </td>
              <td>{rowValidationMessage(row.errors, t)}
                {row.errors && rowValidationMessage(row.errors, t).includes(t('connectData.job.unknownError')) && <details>
                  <summary>{t('connectData.job.technicalDetails')}</summary>
                  <pre dir="ltr">{typeof row.errors === 'string' ? row.errors : JSON.stringify(row.errors, null, 2)}</pre>
                </details>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

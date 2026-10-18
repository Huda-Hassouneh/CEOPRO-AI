import { connectionStatusLabel, jobErrorMessage } from '../../data-connections/utils/connectionPresentation.js';

export function IngestionJobStatusTable({ job, t, formatDate }) {
  if (!job) return null;
  return (
    <dl className="ingestion-job-status-table">
      <div><dt>{t("connectData.job.status")}</dt><dd>{job.rowsTruncated ? t("connectData.job.incomplete") : connectionStatusLabel(job.status, t)}</dd></div>
      <div><dt>{t("connectData.job.source")}</dt><dd>{job.sourceName}</dd></div>
      <div><dt>{t("connectData.job.rowsProcessed")}</dt><dd>{job.rowsProcessed}</dd></div>
      {job.sourceRowCount != null && <div><dt>{t("connectData.job.sourceRows")}</dt><dd>{job.sourceRowCount}</dd></div>}
      {job.rowsTruncated && <div className="ingestion-job-status-table__error"><dt>{t("connectData.job.incomplete")}</dt><dd>{t("connectData.job.truncatedHelp")}</dd></div>}
      <div><dt>{t("connectData.job.rowsFailed")}</dt><dd>{job.rowsFailed}</dd></div>
      <div><dt>{t("connectData.job.rowsPartial")}</dt><dd>{job.rowsPartial}</dd></div>
      <div><dt>{t("connectData.job.attempts")}</dt><dd>{job.processingAttempts}</dd></div>
      <div><dt>{t("connectData.job.created")}</dt><dd>{formatDate(job.createdAt)}</dd></div>
      {job.error && <div className="ingestion-job-status-table__error"><dt>{t("connectData.job.error")}</dt><dd>
        {jobErrorMessage(job.error, t)}
        {jobErrorMessage(job.error, t) === t('connectData.job.unknownError') && <details>
          <summary>{t('connectData.job.technicalDetails')}</summary><pre dir="ltr">{job.error}</pre>
        </details>}
      </dd></div>}
    </dl>
  );
}

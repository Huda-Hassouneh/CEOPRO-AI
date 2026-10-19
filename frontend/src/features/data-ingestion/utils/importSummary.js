// Turns the per-file results of ingestionApi.prepareFiles() into one honest
// notice for the Connect Data page.
//
// Previously the page always said "Files uploaded successfully." whenever at
// least one file was accepted - with no row counts, nothing about rows that
// failed or were skipped as already imported, and no mention of another file
// in the same batch that was rejected outright. A customer importing their
// sales history couldn't tell what actually landed.
//
// `t` is the i18n translate function; `formatNumber` formats counts for the
// current locale.
export function summarizeImport(files, t, formatNumber = (value) => String(value)) {
  const lines = [];
  let anyImported = false;
  let anyProblem = false;

  for (const file of files || []) {
    if (file.status !== 'uploaded') {
      anyProblem = true;
      lines.push(t('connectData.importSummary.fileFailed', { name: file.name, error: file.error || t('connectData.feedback.uploadFailed') }));
      continue;
    }
    const promotion = file.summary?.promotion || {};
    const imported = promotion.rows_promoted ?? 0;
    const duplicates = promotion.rows_duplicate ?? 0;
    // rows_failed at the top level are rows that could not even be read/staged
    // (e.g. an unreadable cell) - they never reach promotion's own counts.
    // Rows left out because a new product would exceed the plan's product
    // limit are reported on their own, not as unreadable rows.
    const overLimit = promotion.rows_over_product_limit ?? 0;
    const failed = (promotion.rows_failed ?? 0) - overLimit + (promotion.rows_skipped_incomplete ?? 0) + (file.summary?.rows_failed ?? 0);
    if (imported > 0) anyImported = true;
    if (failed > 0) anyProblem = true;

    const parts = [t('connectData.importSummary.imported', { count: formatNumber(imported) })];
    if (duplicates > 0) parts.push(t('connectData.importSummary.duplicates', { count: formatNumber(duplicates) }));
    if (failed > 0) parts.push(t('connectData.importSummary.failed', { count: formatNumber(failed) }));
    if (overLimit > 0) {
      anyProblem = true;
      parts.push(t('connectData.importSummary.overProductLimit', { count: formatNumber(overLimit) }));
    }
    lines.push(`${file.name}: ${parts.join(', ')}`);
  }

  let variant = 'success';
  if (!anyImported && anyProblem) variant = 'error';
  else if (anyProblem) variant = 'warning';
  else if (!anyImported) variant = 'info';
  return { variant, message: lines.join(' · ') };
}

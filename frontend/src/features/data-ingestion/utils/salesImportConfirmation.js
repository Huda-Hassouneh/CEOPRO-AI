import { translateCurrent } from '../../../shared/lib/i18n.js';
/** A saved job is not proof that an entire file was received. */
export function confirmSalesImport(payload) {
  const truncated = payload?.rows_truncated_to_limit;
  if (truncated === true || (typeof truncated === "number" && truncated > 0) || payload?.import_complete === false) {
    throw new Error(translateCurrent("interfaceCopy.partialSalesFile"));
  }
  if (typeof payload?.job_id !== "string" || payload.job_id_source !== "ceopro" ||
      (!payload.duplicate && payload.job_status !== "queued")) {
    throw new Error(translateCurrent("interfaceCopy.importJobUnconfirmed"));
  }
  if (Number.isInteger(payload.source_rows_total) && payload.source_rows_total !== payload.staged_row_count) {
    throw new Error(translateCurrent("interfaceCopy.stagedCountMismatch"));
  }
  return payload;
}

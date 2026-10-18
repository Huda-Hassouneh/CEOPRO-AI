// Bound each INSERT for large extracted CSV files without splitting the
// surrounding all-or-nothing database transaction.
export const BUSINESS_FILE_STAGING_BATCH_SIZE = 500;

export async function writeStagingRowsInBatches<Row>(
  rows: readonly Row[],
  writeBatch: (batch: Row[]) => Promise<unknown>
): Promise<void> {
  for (let offset = 0; offset < rows.length; offset += BUSINESS_FILE_STAGING_BATCH_SIZE) {
    await writeBatch(rows.slice(offset, offset + BUSINESS_FILE_STAGING_BATCH_SIZE));
  }
}

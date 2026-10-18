import {ensureImportedProduct, ImportProductError} from "./import-product.js";
import { saleIdentity } from "../service/sale-identity.js";
import { randomUUID } from "node:crypto";
import type { Prisma } from "../../../generated/prisma/client.js";
import { ingestionWorkerPrisma } from "../../../config/ingestion-worker-database.js";
import { parseSalesStagingRow } from "../service/sales-staging-row.js";
import { lockProductCatalog } from "../../products/repo/product-capacity.js";
import { ProductError } from "../../products/types/products.types.js";
import type {
  ClaimedIngestionJob,
  ProcessedIngestionJob
} from "../types/dataconnection.types.js";
// Keep compatibility with workers that import the job types from this module.
export type {
  ClaimedIngestionJob,
  ProcessedIngestionJob
} from "../types/dataconnection.types.js";

export const INGESTION_WORKER_MAX_ATTEMPTS = 5;
// Each batch commits independently: previous COMMITTED rows are never replayed.
// Keep both the batch size and transaction timeout well below the 5-minute lease.
const INGESTION_BATCH_SIZE = 50;
const BATCH_TRANSACTION_TIMEOUT_MS = 60_000;
const CLAIM_LEASE_SECONDS = 5 * 60;
const BASE_RETRY_MS = 30_000;
const MAX_RETRY_MS = 15 * 60 * 1000;

/** Progress notifications are emitted only AFTER a database batch commits. */
export type IngestionJobProgress = {
  phase: "started" | "batch" | "completed";
  jobId: string;
  attempt: number;
  totalRows: number;
  completedRows: number;
  pendingRows: number;
  committedRows: number;
  invalidRows: number;
  partialRows: number;
  batchNumber: number;
  batchRows: number;
  batchDurationMs: number;
};

export type IngestionProgressListener = (
  progress: IngestionJobProgress
) => void;

type ProgressTotals = Pick<
  IngestionJobProgress,
  "totalRows" | "pendingRows" | "committedRows" | "invalidRows" | "partialRows"
>;

/** Count ALL staged statuses, including extraction-time INVALID/PARTIAL rows. */
async function getProgressTotals(
  job: ClaimedIngestionJob
): Promise<ProgressTotals> {
  const groups = await ingestionWorkerPrisma.import_staging_rows.groupBy({
    by: ["validation_status"],
    where: { tenant_id: job.tenant_id, job_id: job.job_id },
    _count: { _all: true }
  });
  const counts = new Map(
    groups.map((group) => [group.validation_status, group._count._all])
  );
  return {
    totalRows: groups.reduce((sum, group) => sum + group._count._all, 0),
    pendingRows: counts.get("PENDING") ?? 0,
    committedRows: counts.get("COMMITTED") ?? 0,
    invalidRows: counts.get("INVALID") ?? 0,
    partialRows: counts.get("PARTIAL") ?? 0
  };
}

/** Diagnostic callbacks must never cause retries after a successful commit. */
function emitProgress(
  onProgress: IngestionProgressListener | undefined,
  value: IngestionJobProgress
): void {
  try {
    onProgress?.(value);
  } catch (error) {
    // Progress logging must not invalidate successfully committed import data.
    console.warn("[DataIngestionWorker] Progress reporter failed", error);
  }
}

function retryDelayMs(attempts: number): number {
  const exponent = Math.max(0, attempts - 1);
  return Math.min(BASE_RETRY_MS * 2 ** exponent, MAX_RETRY_MS);
}

function safeErrorCode(error: unknown): string {
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  ) {
    return (error as { code: string }).code.slice(0, 100);
  }
  return "INGESTION_COMMIT_FAILED";
}


async function lockProcessingJob(
  tx: Prisma.TransactionClient,
  job: ClaimedIngestionJob
): Promise<boolean> {
  const rows = await tx.$queryRaw<Array<{ job_id: string }>>`
    SELECT job_id
    FROM ingestion_jobs
    WHERE tenant_id = ${job.tenant_id}::uuid
      AND job_id = ${job.job_id}::uuid
      AND job_status = 'PROCESSING'
      AND processing_attempts = ${job.processing_attempts}
    FOR UPDATE
  `;
  return rows.length === 1;
}

type BatchResult =
  | { state: "lost" }
  | { state: "continue"; handled: number; committed: number; invalid: number }
  | {
      state: "completed";
      handled: number;
      committed: number;
      quarantined: number;
      partial: number;
      committedInBatch: number;
      invalidInBatch: number;
    };

/**
 * Process at most one small batch in a single transaction. The sales insert,
 * staging COMMITTED marker, and durable job progress all commit together.
 * After a crash/retry, only PENDING rows are eligible for processing.
 */
async function processJobBatchTransaction(
  tx: Prisma.TransactionClient,
  job: ClaimedIngestionJob
): Promise<BatchResult> {
  // Lock the job, and reject a worker holding an expired/reclaimed lease.
  if (!(await lockProcessingJob(tx, job))) return { state: "lost" };

  const rows = await tx.import_staging_rows.findMany({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "PENDING"
    },
    orderBy: { staging_row_id: "asc" },
    take: INGESTION_BATCH_SIZE,
    select: {
      staging_row_id: true,
      raw_payload_json: true
    }
  });

  // Never cache IDs across transactions: a failed transaction rolls back
  // newly created products, so a cross-batch cache could point at missing IDs.
  const productCache = new Map<string, string>();
  if (rows.length) await lockProductCatalog(tx, job.tenant_id);
  let committed = 0;
  let quarantined = 0;
  const sales: Prisma.transactionsCreateManyInput[] = [];
  const stagedSales: Array<{ stagingRowId: bigint; transactionId: string }> = [];

  const identities = new Map<string, { transaction_id: string; payload_sha256: string }>();
  const newIdentities: Array<{ source_system: string; sale_id: string; transaction_id: string; payload_sha256: string }> = [];

  for (const row of rows) {
    const parsed = parseSalesStagingRow(row.raw_payload_json);
    if (!parsed.ok) {
      await tx.import_staging_rows.update({
        where: { staging_row_id: row.staging_row_id },
        data: {
          validation_status: "INVALID",
          validation_errors: parsed.error,
          committed_record_id: null,
          committed_table: null
        }
      });
      quarantined += 1;
      continue;
    }

    let identity: ReturnType<typeof saleIdentity>;
    try { identity = saleIdentity(row.raw_payload_json, parsed.value); }
    catch (error) {
      await tx.import_staging_rows.update({ where: { staging_row_id: row.staging_row_id }, data: {
        validation_status: "INVALID", validation_errors: (error as Error).message
      } });
      quarantined += 1;
      continue;
    }
    if (identity) {
      const existing = identities.get(identity.key) ?? (await tx.$queryRaw<Array<{ transaction_id: string; payload_sha256: string }>>`
        SELECT transaction_id, payload_sha256 FROM public.import_sale_identities
        WHERE tenant_id = ${job.tenant_id}::uuid AND source_system = ${identity.sourceSystem} AND sale_id = ${identity.saleId}
      `)[0];
      if (existing) {
        const matches = existing.payload_sha256 === identity.hash;
        await tx.import_staging_rows.update({ where: { staging_row_id: row.staging_row_id }, data: {
          validation_status: matches ? "COMMITTED" : "INVALID",
          validation_errors: matches ? "Existing sale reused by stable source_system/sale_id." : "SALE_ID_CONFLICT: this sale_id already exists with different sale data; review the source file.",
          committed_record_id: matches ? existing.transaction_id : null,
          committed_table: matches ? "transactions" : null
        } });
        if (matches) committed += 1; else quarantined += 1;
        continue;
      }
    }

    let productId: string;
    try { productId = await ensureImportedProduct(
      tx,
      job.tenant_id,
      parsed.value.productName,
      parsed.value.unitPrice,
      parsed.value.currency,
      job.job_id,
      productCache,
      parsed.value.sku ?? null
    ); } catch (error) {
      if (!(error instanceof ImportProductError) && !(error instanceof ProductError)) throw error;
      await tx.import_staging_rows.update({ where: { staging_row_id: row.staging_row_id }, data: {
        validation_status: "INVALID", validation_errors: error instanceof ProductError
          ? "The active product limit has been reached or is unavailable. Existing products can still be imported." : error.message,
        committed_record_id: null, committed_table: null
      } });
      quarantined += 1;
      continue;
    }

    const transactionId = randomUUID();
    if (identity) {
      identities.set(identity.key, { transaction_id: transactionId, payload_sha256: identity.hash });
      newIdentities.push({ source_system: identity.sourceSystem, sale_id: identity.saleId, transaction_id: transactionId, payload_sha256: identity.hash });
    }
    sales.push({
      transaction_id: transactionId,
      tenant_id: job.tenant_id,
      product_id: productId,
      quantity_sold: parsed.value.quantity,
      unit_price: parsed.value.unitPrice,
      total_price: parsed.value.totalPrice,
      original_currency: parsed.value.currency,
      transaction_date: parsed.value.transactionDate,
      sale_source: "IMPORT"
    });
    stagedSales.push({ stagingRowId: row.staging_row_id, transactionId });
  }

  if (sales.length > 0) {
    // Keep the sale insert and its staging markers in this same transaction.
    // One insert and one update per batch avoid two network round trips per row.
    const inserted = await tx.transactions.createMany({ data: sales });
    if (inserted.count !== sales.length) {
      throw new Error("Not every staged sale was inserted; rolling back the batch.");
    }

    if (newIdentities.length) {
      await tx.$executeRaw`
        INSERT INTO public.import_sale_identities(tenant_id,source_system,sale_id,transaction_id,payload_sha256)
        SELECT ${job.tenant_id}::uuid, i.source_system, i.sale_id, i.transaction_id, i.payload_sha256
        FROM jsonb_to_recordset(${JSON.stringify(newIdentities)}::jsonb)
          AS i(source_system text, sale_id text, transaction_id uuid, payload_sha256 text)
      `;
    }
    const pairs = stagedSales.map((_, index) =>
      `($${2 * index + 1}::bigint, $${2 * index + 2}::uuid)`
    ).join(", ");
    const parameters: Array<string | bigint> = stagedSales.flatMap((item) =>
      [item.stagingRowId, item.transactionId]
    );
    parameters.push(job.tenant_id, job.job_id);
    const updated = await tx.$executeRawUnsafe(
      `UPDATE import_staging_rows AS staging
       SET validation_status = 'COMMITTED', validation_errors = NULL,
           committed_record_id = sale.transaction_id,
           committed_table = 'transactions'
       FROM (VALUES ${pairs}) AS sale(staging_row_id, transaction_id)
       WHERE staging.staging_row_id = sale.staging_row_id
         AND staging.tenant_id = $${parameters.length - 1}::uuid
         AND staging.job_id = $${parameters.length}::uuid
         AND staging.validation_status = 'PENDING'`,
      ...parameters
    );
    if (updated !== stagedSales.length) {
      throw new Error("Not every staging marker was saved; rolling back the batch.");
    }
    committed += stagedSales.length;
  }

  const now = new Date();
  // Refresh the lease after every committed batch, preventing a second worker
  // from reclaiming an active long-running import while the first is working.
  await tx.ingestion_jobs.update({
    where: {
      tenant_id_job_id: {
        tenant_id: job.tenant_id,
        job_id: job.job_id
      }
    },
    data: {
      rows_processed: { increment: committed },
      rows_failed: { increment: quarantined },
      rows_quarantined: { increment: quarantined },
      heartbeat_at: now,
      next_attempt_at: new Date(now.getTime() + CLAIM_LEASE_SECONDS * 1000)
    }
  });

  // A full batch may be the last batch. If any PENDING rows remain, continue;
  // otherwise finish in this same transaction with authoritative counts.
  if (rows.length === INGESTION_BATCH_SIZE) {
    return {
      state: "continue",
      handled: rows.length,
      committed,
      invalid: quarantined
    };
  }
  const pending = await tx.import_staging_rows.count({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "PENDING"
    }
  });
  if (pending > 0) {
    return {
      state: "continue",
      handled: rows.length,
      committed,
      invalid: quarantined
    };
  }

  // Include rows marked INVALID or PARTIAL by extraction before the worker ran.
  // PARTIAL rows are held for review, not silently promoted into transactions.
  const committedTotal = await tx.import_staging_rows.count({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "COMMITTED"
    }
  });
  const invalidTotal = await tx.import_staging_rows.count({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "INVALID"
    }
  });
  const partialTotal = await tx.import_staging_rows.count({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "PARTIAL"
    }
  });

  await tx.ingestion_jobs.update({
    where: {
      tenant_id_job_id: {
        tenant_id: job.tenant_id,
        job_id: job.job_id
      }
    },
    data: {
      job_status: "COMPLETED",
      rows_processed: committedTotal,
      rows_failed: invalidTotal,
      rows_quarantined: invalidTotal,
      rows_partial: partialTotal,
      error_log:
        invalidTotal > 0 || partialTotal > 0
          ? `${invalidTotal} invalid row(s); ${partialTotal} partial row(s) require review.`
          : null,
      heartbeat_at: null,
      ended_at: new Date()
    }
  });

  return {
    state: "completed",
    handled: rows.length,
    committed: committedTotal,
    quarantined: invalidTotal,
    partial: partialTotal,
    committedInBatch: committed,
    invalidInBatch: quarantined
  };
}

export const ingestionWorkerRepo = {
  markExhaustedLeasesFailed: async (): Promise<number> => {
    return ingestionWorkerPrisma.$executeRaw`
      UPDATE ingestion_jobs
      SET job_status = 'FAILED',
          ended_at = CURRENT_TIMESTAMP,
          heartbeat_at = NULL,
          error_log = 'INGESTION_MAX_ATTEMPTS_EXCEEDED'
      WHERE job_status IN ('QUEUED', 'PROCESSING')
        AND processing_attempts >= ${INGESTION_WORKER_MAX_ATTEMPTS}
        AND next_attempt_at <= CURRENT_TIMESTAMP
    `;
  },

  claimPendingJobs: async (limit = 5): Promise<ClaimedIngestionJob[]> => {
    return ingestionWorkerPrisma.$queryRaw<ClaimedIngestionJob[]>`
      WITH due_jobs AS MATERIALIZED (
        SELECT j.tenant_id, j.job_id
        FROM ingestion_jobs j
        JOIN data_sources s
          ON s.tenant_id = j.tenant_id
         AND s.source_id = j.source_id
         AND s.source_type = 'documents'
        WHERE j.processing_attempts < ${INGESTION_WORKER_MAX_ATTEMPTS}
          AND (
            (j.job_status = 'QUEUED' AND j.next_attempt_at <= CURRENT_TIMESTAMP)
            OR
            (j.job_status = 'PROCESSING' AND j.next_attempt_at <= CURRENT_TIMESTAMP)
            OR
            (
              j.job_status = 'COMPLETED'
              AND j.next_attempt_at <= CURRENT_TIMESTAMP
              AND EXISTS (
                SELECT 1
                FROM import_staging_rows pending
                WHERE pending.tenant_id = j.tenant_id
                  AND pending.job_id = j.job_id
                  AND pending.validation_status = 'PENDING'
              )
            )
          )
        ORDER BY j.next_attempt_at, j.created_at, j.job_id
        FOR UPDATE OF j SKIP LOCKED
        LIMIT ${limit}
      )
      UPDATE ingestion_jobs j
      SET job_status = 'PROCESSING',
          processing_attempts = j.processing_attempts + 1,
          started_at = COALESCE(j.started_at, CURRENT_TIMESTAMP),
          heartbeat_at = CURRENT_TIMESTAMP,
          next_attempt_at = CURRENT_TIMESTAMP + make_interval(secs => ${CLAIM_LEASE_SECONDS}),
          ended_at = NULL,
          error_log = NULL
      FROM due_jobs d
      WHERE j.tenant_id = d.tenant_id
        AND j.job_id = d.job_id
      RETURNING j.tenant_id, j.job_id, j.processing_attempts
    `;
  },

  processClaimedJob: async (
    job: ClaimedIngestionJob,
    onProgress?: IngestionProgressListener
  ): Promise<ProcessedIngestionJob | null> => {
    // Load the baseline once. Already-COMMITTED rows from a previous attempt
    // count as completed; retries do not start their progress at zero.
    const totals = await getProgressTotals(job);
    let batchNumber = 0;
    const report = (
      phase: IngestionJobProgress["phase"],
      batchRows: number,
      batchDurationMs: number
    ): void =>
      emitProgress(onProgress, {
        phase,
        jobId: job.job_id,
        attempt: job.processing_attempts,
        ...totals,
        completedRows: totals.totalRows - totals.pendingRows,
        batchNumber,
        batchRows,
        batchDurationMs
      });
    report("started", 0, 0);

    // Each transaction contains at most INGESTION_BATCH_SIZE staged rows.
    // Report AFTER $transaction resolves so the UI never counts rolled-back data.
    for (;;) {
      const batchStartedAt = Date.now();
      const result = await ingestionWorkerPrisma.$transaction(
        (tx) => processJobBatchTransaction(tx, job),
        { maxWait: 10_000, timeout: BATCH_TRANSACTION_TIMEOUT_MS }
      );
      if (result.state === "lost") return null;

      if (result.handled > 0) {
        batchNumber += 1;
        totals.pendingRows = Math.max(0, totals.pendingRows - result.handled);
        totals.committedRows +=
          result.state === "completed"
            ? result.committedInBatch
            : result.committed;
        totals.invalidRows +=
          result.state === "completed" ? result.invalidInBatch : result.invalid;
      }
      const duration = Date.now() - batchStartedAt;
      if (result.state === "completed") {
        // The last transaction has finalized these authoritative DB totals.
        totals.committedRows = result.committed;
        totals.invalidRows = result.quarantined;
        totals.partialRows = result.partial;
        totals.pendingRows = 0;
        report("completed", result.handled, duration);
        return {
          jobId: job.job_id,
          committed: result.committed,
          quarantined: result.quarantined
        };
      }
      report("batch", result.handled, duration);
    }
  },

  scheduleRetryOrFail: async (
    job: ClaimedIngestionJob,
    error: unknown
  ): Promise<void> => {
    const exhausted = job.processing_attempts >= INGESTION_WORKER_MAX_ATTEMPTS;
    const nextAttemptAt = new Date(
      Date.now() + retryDelayMs(job.processing_attempts)
    );
    await ingestionWorkerPrisma.ingestion_jobs.updateMany({
      where: {
        tenant_id: job.tenant_id,
        job_id: job.job_id,
        job_status: "PROCESSING",
        processing_attempts: job.processing_attempts
      },
      data: {
        job_status: exhausted ? "FAILED" : "QUEUED",
        next_attempt_at: exhausted ? new Date() : nextAttemptAt,
        heartbeat_at: null,
        ended_at: exhausted ? new Date() : null,
        error_log: safeErrorCode(error)
      }
    });
  }
};

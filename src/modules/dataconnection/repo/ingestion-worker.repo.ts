import { randomUUID } from "node:crypto";
import type { Prisma } from "../../../generated/prisma/client.js";
import { ingestionWorkerPrisma } from "../../../config/ingestion-worker-database.js";
import { parseSalesStagingRow } from "../service/sales-staging-row.js";

export const INGESTION_WORKER_MAX_ATTEMPTS = 5;
const CLAIM_LEASE_SECONDS = 5 * 60;
const BASE_RETRY_MS = 30_000;
const MAX_RETRY_MS = 15 * 60 * 1000;

export type ClaimedIngestionJob = {
  tenant_id: string;
  job_id: string;
  processing_attempts: number;
};

export type ProcessedIngestionJob = {
  jobId: string;
  committed: number;
  quarantined: number;
};

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

async function ensureImportedProduct(
  tx: Prisma.TransactionClient,
  tenantId: string,
  productName: string,
  unitPrice: string,
  currency: string,
  jobId: string,
  productCache: Map<string, string>
): Promise<string> {
  const normalizedName = productName.trim().toLocaleLowerCase("en-US");
  const cacheKey = `${tenantId}:${normalizedName}`;
  const cached = productCache.get(cacheKey);
  if (cached) return cached;

  // Serialize matching-product creation across concurrent imports for the
  // same tenant/name pair. The returned column is UUID (never PostgreSQL void).
  const lockKey = cacheKey;
  const matches = await tx.$queryRaw<Array<{ product_id: string | null }>>`
    WITH product_name_lock AS MATERIALIZED (
      SELECT pg_advisory_xact_lock(hashtextextended(${lockKey}, 0))
    )
    SELECT existing.product_id
    FROM product_name_lock
    LEFT JOIN LATERAL (
      SELECT p.product_id
      FROM products p
      WHERE p.tenant_id = ${tenantId}::uuid
        AND p.deleted_at IS NULL
        AND lower(btrim(coalesce(
          NULLIF(p.product_name ->> 'en', ''),
          NULLIF(p.product_name ->> 'name', ''),
          p.product_name #>> '{}',
          ''
        ))) = ${normalizedName}
      ORDER BY p.created_at ASC NULLS FIRST, p.product_id ASC
      LIMIT 1
    ) AS existing ON TRUE
  `;

  const existingId = matches[0]?.product_id;
  if (existingId) {
    productCache.set(cacheKey, existingId);
    return existingId;
  }

  const product = await tx.products.create({
    data: {
      product_id: randomUUID(),
      tenant_id: tenantId,
      product_name: { en: productName },
      current_price: unitPrice,
      currency,
      source: "IMPORTED",
      metadata: {
        import_job_id: jobId,
        import_source: "data_connection"
      }
    },
    select: { product_id: true }
  });

  productCache.set(cacheKey, product.product_id);
  return product.product_id;
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
    FOR UPDATE
  `;
  return rows.length === 1;
}

async function processJobTransaction(
  tx: Prisma.TransactionClient,
  job: ClaimedIngestionJob
): Promise<ProcessedIngestionJob | null> {
  if (!(await lockProcessingJob(tx, job))) return null;

  const rows = await tx.import_staging_rows.findMany({
    where: {
      tenant_id: job.tenant_id,
      job_id: job.job_id,
      validation_status: "PENDING"
    },
    orderBy: { staging_row_id: "asc" },
    select: {
      staging_row_id: true,
      raw_payload_json: true
    }
  });

  const productCache = new Map<string, string>();
  let committed = 0;
  let quarantined = 0;

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

    const productId = await ensureImportedProduct(
      tx,
      job.tenant_id,
      parsed.value.productName,
      parsed.value.unitPrice,
      parsed.value.currency,
      job.job_id,
      productCache
    );

    const transaction = await tx.transactions.create({
      data: {
        transaction_id: randomUUID(),
        tenant_id: job.tenant_id,
        product_id: productId,
        quantity_sold: parsed.value.quantity,
        unit_price: parsed.value.unitPrice,
        total_price: parsed.value.totalPrice,
        original_currency: parsed.value.currency,
        transaction_date: parsed.value.transactionDate,
        sale_source: "IMPORT"
      },
      select: { transaction_id: true }
    });

    await tx.import_staging_rows.update({
      where: { staging_row_id: row.staging_row_id },
      data: {
        validation_status: "COMMITTED",
        validation_errors: null,
        committed_record_id: transaction.transaction_id,
        committed_table: "transactions"
      }
    });
    committed += 1;
  }

  await tx.ingestion_jobs.update({
    where: {
      tenant_id_job_id: {
        tenant_id: job.tenant_id,
        job_id: job.job_id
      }
    },
    data: {
      job_status: "COMPLETED",
      rows_processed: committed,
      rows_failed: quarantined,
      rows_quarantined: quarantined,
      error_log: quarantined > 0
        ? `${quarantined} staged row(s) failed business-field validation.`
        : null,
      heartbeat_at: null,
      ended_at: new Date()
    }
  });

  return { jobId: job.job_id, committed, quarantined };
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
    job: ClaimedIngestionJob
  ): Promise<ProcessedIngestionJob | null> => {
    return ingestionWorkerPrisma.$transaction(
      (tx) => processJobTransaction(tx, job),
      { maxWait: 10_000, timeout: 180_000 }
    );
  },

  scheduleRetryOrFail: async (
    job: ClaimedIngestionJob,
    error: unknown
  ): Promise<void> => {
    const exhausted = job.processing_attempts >= INGESTION_WORKER_MAX_ATTEMPTS;
    const nextAttemptAt = new Date(Date.now() + retryDelayMs(job.processing_attempts));
    await ingestionWorkerPrisma.ingestion_jobs.updateMany({
      where: {
        tenant_id: job.tenant_id,
        job_id: job.job_id,
        job_status: "PROCESSING"
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

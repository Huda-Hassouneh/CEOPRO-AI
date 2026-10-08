import { ingestionWorkerPrisma } from "../config/ingestion-worker-database.js";
import {
  ingestionWorkerRepo,
  type ClaimedIngestionJob
} from "../modules/dataconnection/repo/ingestion-worker.repo.js";

const POLL_INTERVAL_MS = 10_000;
const CLAIM_BATCH_SIZE = 1;

let running = true;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function databaseErrorCode(error: unknown): string {
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  ) {
    return (error as { code: string }).code.slice(0, 100);
  }
  return "INGESTION_WORKER_ERROR";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function stringField(
  record: Record<string, unknown> | null,
  ...keys: string[]
): string | undefined {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function sanitizeDiagnosticMessage(message: string): string {
  return message
    .replace(/postgres(?:ql)?:\/\/\S+/gi, "[redacted-database-url]")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[redacted-email]")
    .replace(/\b(?:Bearer\s+)[A-Z0-9._~-]+/gi, "Bearer [redacted]")
    .replace(/\b(password|token|secret)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
    .replace(/\s+/g, " ")
    .slice(0, 600);
}

function databaseErrorDiagnostic(error: unknown): string {
  const root = asRecord(error);
  const meta = asRecord(root?.meta);
  const adapter = asRecord(meta?.driverAdapterError);
  const cause = asRecord(adapter?.cause) ?? asRecord(root?.cause);
  const nestedCause = asRecord(cause?.cause);
  const diagnostic: Record<string, string> = {};

  const driverCode =
    stringField(cause, "code", "originalCode") ??
    stringField(nestedCause, "code", "originalCode");
  const causeKind =
    stringField(cause, "kind") ?? stringField(nestedCause, "kind");
  const constraint =
    stringField(cause, "constraint", "constraintName") ??
    stringField(nestedCause, "constraint", "constraintName");
  const table =
    stringField(cause, "table") ?? stringField(nestedCause, "table");
  const column =
    stringField(cause, "column") ?? stringField(nestedCause, "column");

  if (driverCode) diagnostic.driverCode = driverCode;
  if (causeKind) diagnostic.causeKind = causeKind;
  if (constraint) diagnostic.constraint = constraint;
  if (table) diagnostic.table = table;
  if (column) diagnostic.column = column;

  if (process.env.NODE_ENV !== "production") {
    const message =
      stringField(cause, "message", "originalMessage") ??
      stringField(nestedCause, "message", "originalMessage") ??
      stringField(root, "message");
    if (message) diagnostic.message = sanitizeDiagnosticMessage(message);
  }

  return JSON.stringify(diagnostic);
}

async function processJob(job: ClaimedIngestionJob): Promise<void> {
  try {
    const result = await ingestionWorkerRepo.processClaimedJob(job);
    if (!result) return;

    console.info(
      `[DataIngestionWorker] Job completed | job=${result.jobId} committed=${result.committed} quarantined=${result.quarantined}`
    );
  } catch (error) {
    const code = databaseErrorCode(error);
    console.error(
      `[DataIngestionWorker] Job failed | job=${job.job_id} code=${code} diagnostic=${databaseErrorDiagnostic(error)}`
    );
    const err = error as {
      code?: string;
      message?: string;
      meta?: { code?: string; message?: string };
    };

    console.error("[DataIngestionWorker] Poll failed", {
      prismaCode: err.code,
      databaseCode: err.meta?.code,
      databaseMessage: err.meta?.message,
      message: err.message
    });
    try {
      await ingestionWorkerRepo.scheduleRetryOrFail(job, error);
    } catch (retryError) {
      console.error(
        `[DataIngestionWorker] Could not schedule retry | job=${job.job_id} code=${databaseErrorCode(retryError)}`
      );
      const err = retryError as {
        code?: string;
        message?: string;
        meta?: { code?: string; message?: string };
      };

      console.error("[DataIngestionWorker] Poll failed", {
        prismaCode: err.code,
        databaseCode: err.meta?.code,
        databaseMessage: err.meta?.message,
        message: err.message
      });
    }
  }
}

export async function runDataIngestionWorker(): Promise<void> {
  console.info(
    `[DataIngestionWorker] Started | poll_interval_ms=${POLL_INTERVAL_MS}`
  );

  try {
    while (running) {
      const cycleStartedAt = Date.now();
      try {
        const exhausted = await ingestionWorkerRepo.markExhaustedLeasesFailed();
        if (exhausted > 0) {
          console.error(
            `[DataIngestionWorker] Exhausted jobs marked failed | count=${exhausted}`
          );
        }

        const jobs =
          await ingestionWorkerRepo.claimPendingJobs(CLAIM_BATCH_SIZE);
        for (const job of jobs) {
          if (!running) break;
          await processJob(job);
        }
      } catch (error) {
        console.error(
          `[DataIngestionWorker] Poll failed | code=${databaseErrorCode(error)}`
        );
        const err = error as {
          code?: string;
          message?: string;
          meta?: { code?: string; message?: string };
        };

        console.error("[DataIngestionWorker] Poll failed", {
          prismaCode: err.code,
          databaseCode: err.meta?.code,
          databaseMessage: err.meta?.message,
          message: err.message
        });
      }

      const waitMs = Math.max(
        0,
        POLL_INTERVAL_MS - (Date.now() - cycleStartedAt)
      );
      if (running && waitMs > 0) await sleep(waitMs);
    }
  } finally {
    await ingestionWorkerPrisma.$disconnect();
    console.info("[DataIngestionWorker] Stopped");
  }
}

process.on("SIGTERM", () => {
  running = false;
});

process.on("SIGINT", () => {
  running = false;
});

runDataIngestionWorker().catch(async (error) => {
  console.error(
    `[DataIngestionWorker] Fatal error | code=${databaseErrorCode(error)}`
  );
  await ingestionWorkerPrisma.$disconnect();
  process.exit(1);
});

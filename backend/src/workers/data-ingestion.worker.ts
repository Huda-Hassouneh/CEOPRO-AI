import * as readline from "node:readline";
import { ingestionWorkerPrisma } from "../config/ingestion-worker-database.js";
import {
  ingestionWorkerRepo,
  type ClaimedIngestionJob,
  type IngestionJobProgress
} from "../modules/dataconnection/repo/ingestion-worker.repo.js";

const POLL_INTERVAL_MS = 10_000;
const CLAIM_BATCH_SIZE = 1;

const SPINNER_FRAMES = ["|", "/", "-", "\\"];
const SPINNER_INTERVAL_MS = 150;

function formatDuration(ms: number): string {
  const seconds = Math.floor(Math.max(0, ms) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${minutes}m${String(rest).padStart(2, "0")}s`;
}

/** One-line progress animation on a TTY; one durable log entry per batch elsewhere. */
class IngestionProgressDisplay {
  private readonly interactive = Boolean(process.stdout.isTTY);
  private readonly startedAt = Date.now();
  private readonly jobId: string;
  private timer: ReturnType<typeof setInterval> | null = null;
  private latest: IngestionJobProgress | null = null;
  private baselineCompleted = 0;
  private frame = 0;
  private hasRendered = false;

  constructor(jobId: string) {
    this.jobId = jobId;
  }

  start(): void {
    if (!this.interactive) return;
    this.timer = setInterval(() => this.render(), SPINNER_INTERVAL_MS);
    this.timer.unref();
    this.render();
  }

  onProgress = (progress: IngestionJobProgress): void => {
    if (progress.phase === "started") {
      this.baselineCompleted = progress.completedRows;
    }
    this.latest = progress;
    if (this.interactive) {
      this.render();
    } else if (progress.phase === "started" || progress.phase === "batch") {
      console.info(`[DataIngestionWorker] ${this.summary(progress)}`);
    }
  };

  private summary(progress: IngestionJobProgress): string {
    const total = progress.totalRows;
    const done = progress.completedRows;
    const percent = total === 0 ? 100 : Math.min(100, (done / total) * 100);
    const filled = Math.round((percent / 100) * 22);
    const bar = "#".repeat(filled) + "-".repeat(22 - filled);
    const elapsed = Date.now() - this.startedAt;
    const newlyDone = Math.max(0, done - this.baselineCompleted);
    const rate = elapsed > 0 ? newlyDone / (elapsed / 1000) : 0;
    const eta =
      rate > 0 && progress.pendingRows > 0
        ? formatDuration((progress.pendingRows / rate) * 1000)
        : "--";
    const marker =
      progress.phase === "started"
        ? "started"
        : `batch=${progress.batchNumber}`;

    return (
      `${this.jobId.slice(0, 8)} [${bar}] ${percent.toFixed(1)}% ` +
      `${done}/${total} ${marker} saved=${progress.committedRows} ` +
      `bad=${progress.invalidRows} partial=${progress.partialRows} ` +
      `${formatDuration(elapsed)} ETA=${eta}`
    );
  }

  private render(): void {
    if (!this.interactive) return;
    const spinner = SPINNER_FRAMES[this.frame++ % SPINNER_FRAMES.length];
    const body = this.latest
      ? this.summary(this.latest)
      : `job=${this.jobId.slice(0, 8)} preparing rows...`;
    // Avoid terminal wrapping that could leave multiple visible progress lines.
    const width = Math.max(30, (process.stdout.columns ?? 120) - 1);
    const line = `[DataIngestionWorker] ${spinner} ${body}`.slice(0, width);
    readline.clearLine(process.stdout, 0);
    readline.cursorTo(process.stdout, 0);
    process.stdout.write(line);
    this.hasRendered = true;
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.interactive && this.hasRendered) {
      readline.clearLine(process.stdout, 0);
      readline.cursorTo(process.stdout, 0);
      this.hasRendered = false;
    }
  }
}

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
  const display = new IngestionProgressDisplay(job.job_id);
  display.start();
  try {
    const result = await ingestionWorkerRepo.processClaimedJob(
      job,
      display.onProgress
    );
    display.stop();
    if (!result) {
      console.warn(`[DataIngestionWorker] Job lease lost | job=${job.job_id}`);
      return;
    }

    console.info(
      `[DataIngestionWorker] Job completed | job=${result.jobId} committed=${result.committed} quarantined=${result.quarantined}`
    );
  } catch (error) {
    display.stop();
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
  } finally {
    display.stop();
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

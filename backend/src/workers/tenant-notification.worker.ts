import { dispatchTenantNotification } from "../modules/tenant-notifications/tenant-notification.dispatcher.js";
import { tenantNotificationRepo } from "../modules/tenant-notifications/repo/tenant-notification.repo.js";

const POLL_INTERVAL_MS = 10_000;
const BATCH_SIZE = 20;
const MAX_ATTEMPTS = 5;
const BASE_RETRY_MS = 30_000;
const MAX_RETRY_MS = 15 * 60 * 1000;

let running = true;

function sleep(ms: number) {
  return new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  });
}

function retryAt(attempts: number): Date {
  const exponent = Math.max(0, attempts - 1);
  const delay = Math.min(BASE_RETRY_MS * 2 ** exponent, MAX_RETRY_MS);
  return new Date(Date.now() + delay);
}

function errorCode(error: unknown): string {
  if (
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof (error as { code?: unknown }).code === "string"
  ) {
    return (error as { code: string }).code.slice(0, 100);
  }

  return "TENANT_NOTIFICATION_DISPATCH_FAILED";
}

async function handleDispatchFailure(
  event: Awaited<ReturnType<typeof tenantNotificationRepo.claimDueEvents>>[number],
  error: unknown
): Promise<void> {
  const code = errorCode(error);

  if (event.attempts >= MAX_ATTEMPTS) {
    const markedFailed = await tenantNotificationRepo.markOutboxFailed(
      event.id,
      code
    );

    if (!markedFailed) {
      console.error(
        `[TenantNotificationWorker] Could not mark failed | outbox=${event.id}`
      );
    }

    return;
  }

  const nextAttemptAt = retryAt(event.attempts);
  const rescheduled = await tenantNotificationRepo.rescheduleOutboxEvent(
    event.id,
    {
      nextAttemptAt,
      errorCode: code
    }
  );

  if (!rescheduled) {
    console.error(
      `[TenantNotificationWorker] Could not reschedule | outbox=${event.id}`
    );
  }
}

async function runWorker(): Promise<void> {
  console.info("[TenantNotificationWorker] Started");

  while (running) {
    let events;

    try {
      events = await tenantNotificationRepo.claimDueEvents(BATCH_SIZE);
    } catch (error) {
      console.error("[TenantNotificationWorker] Poll failed", error);
      await sleep(POLL_INTERVAL_MS);
      continue;
    }

    if (events.length === 0) {
      await sleep(POLL_INTERVAL_MS);
      continue;
    }

    for (const event of events) {
      if (!running) break;

      try {
        await dispatchTenantNotification(event);
      } catch (error) {
        console.error(
          `[TenantNotificationWorker] Failed event ${event.id}`,
          error
        );

        try {
          await handleDispatchFailure(event, error);
        } catch (retryError) {
          console.error(
            `[TenantNotificationWorker] Failed to update retry state ${event.id}`,
            retryError
          );
        }
      }
    }
  }

  console.info("[TenantNotificationWorker] Stopped");
}

process.on("SIGTERM", () => {
  running = false;
});

process.on("SIGINT", () => {
  running = false;
});

runWorker().catch((error) => {
  console.error("[TenantNotificationWorker] Fatal error", error);
  process.exit(1);
});

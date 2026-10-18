import { dispatchPlatformNotification } from "../modules/platform-notifications/platform-notification.dispatcher.js";
import { platformNotificationRepo } from "../modules/platform-notifications/repo/platform-notification.repo.js";

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

  return "PLATFORM_NOTIFICATION_DISPATCH_FAILED";
}

async function handleDispatchFailure(
  event: Awaited<ReturnType<typeof platformNotificationRepo.claimDueEvents>>[number],
  error: unknown
): Promise<void> {
  const code = errorCode(error);

  if (event.attempts >= MAX_ATTEMPTS) {
    const markedFailed = await platformNotificationRepo.markOutboxFailed(
      event.id,
      code
    );

    if (!markedFailed) {
      console.error(
        `[PlatformNotificationWorker] Could not mark failed | outbox=${event.id}`
      );
    }

    return;
  }

  const nextAttemptAt = retryAt(event.attempts);
  const rescheduled = await platformNotificationRepo.rescheduleOutboxEvent(
    event.id,
    {
      nextAttemptAt,
      errorCode: code
    }
  );

  if (!rescheduled) {
    console.error(
      `[PlatformNotificationWorker] Could not reschedule | outbox=${event.id}`
    );
  }
}

async function runWorker(): Promise<void> {
  console.info("[PlatformNotificationWorker] Started");

  while (running) {
    let events;

    try {
      events = await platformNotificationRepo.claimDueEvents(BATCH_SIZE);
    } catch (error) {
      console.error("[PlatformNotificationWorker] Poll failed", error);
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
        await dispatchPlatformNotification(event);
      } catch (error) {
        console.error(
          `[PlatformNotificationWorker] Failed event ${event.id}`,
          error
        );

        try {
          await handleDispatchFailure(event, error);
        } catch (retryError) {
          // The row remains processing. Its claim lease will eventually expire,
          // so another poll/worker can recover it.
          console.error(
            `[PlatformNotificationWorker] Failed to update retry state ${event.id}`,
            retryError
          );
        }
      }
    }
  }

  console.info("[PlatformNotificationWorker] Stopped");
}

process.on("SIGTERM", () => {
  running = false;
});

process.on("SIGINT", () => {
  running = false;
});

runWorker().catch((error) => {
  console.error("[PlatformNotificationWorker] Fatal error", error);
  process.exit(1);
});

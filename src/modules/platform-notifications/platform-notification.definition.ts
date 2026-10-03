import type {
  PaymentFailedPayload,
  PlatformNotificationOutboxEvent
} from "./platform-notification.types.js";

export type PlatformNotificationDefinition = {
  severity: "INFO" | "WARNING" | "CRITICAL";
  titleKey: string;
  bodyKey: string;
  resourceType: string | null;
  resourceId: string | null;
  payload: Record<string, unknown>;
  recipientPolicy: {
    requiredPermissions: string[];
    permissionMode: "ANY" | "ALL";
  };
};

function readPaymentFailedPayload(
  event: PlatformNotificationOutboxEvent
): PaymentFailedPayload {
  const payload = event.payload;

  const subscriptionId = payload.subscriptionId;
  const stripeEventId = payload.stripeEventId;
  const stripeInvoiceId = payload.stripeInvoiceId;
  const paymentIntentId = payload.paymentIntentId;
  const failureReason = payload.failureReason;

  if (
    typeof subscriptionId !== "string" ||
    !subscriptionId ||
    typeof stripeEventId !== "string" ||
    !stripeEventId ||
    typeof stripeInvoiceId !== "string" ||
    !stripeInvoiceId ||
    !(
      paymentIntentId === null ||
      typeof paymentIntentId === "string"
    ) ||
    typeof failureReason !== "string" ||
    !failureReason
  ) {
    throw new Error(
      `Invalid PAYMENT_FAILED payload for outbox event ${event.id}`
    );
  }

  return {
    subscriptionId,
    stripeEventId,
    stripeInvoiceId,
    paymentIntentId,
    failureReason
  };
}

export function buildPlatformNotification(
  event: PlatformNotificationOutboxEvent
): PlatformNotificationDefinition {
  switch (event.event_type) {
    case "PAYMENT_FAILED": {
      const payload = readPaymentFailedPayload(event);

      return {
        severity: "CRITICAL",
        titleKey: "platformNotifications.paymentFailed.title",
        bodyKey: "platformNotifications.paymentFailed.body",
        resourceType: "subscription",
        resourceId: payload.subscriptionId,
        recipientPolicy: {
          requiredPermissions: ["billing.read"],
          permissionMode: "ANY"
        },
        payload: {
          stripeEventId: payload.stripeEventId,
          stripeInvoiceId: payload.stripeInvoiceId,
          paymentIntentId: payload.paymentIntentId,
          failureReason: payload.failureReason
        }
      };
    }

    default:
      throw new Error(
        `Unsupported platform notification event: ${event.event_type}`
      );
  }
}

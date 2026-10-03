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
export function buildPlatformNotification(
  event: PlatformNotificationOutboxEvent
): PlatformNotificationDefinition {
  switch (event.event_type) {
    case "PAYMENT_FAILED": {
      const payload = event.payload as unknown as PaymentFailedPayload;

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

import type {
  CustomPlanOfferReadyPayload,
  TenantNotificationOutboxEvent
} from "./tenant-notification.types.js";

export type TenantNotificationDefinition = {
  severity: "INFO" | "WARNING" | "CRITICAL";
  titleKey: string;
  bodyKey: string;
  resourceType: string | null;
  resourceId: string | null;
  expiresAt: Date | null;
  payload: Record<string, unknown>;
  recipientPolicy: {
    requiredPermissions: string[];
    permissionMode: "ANY" | "ALL";
  };
};

function readCustomPlanOfferReadyPayload(
  event: TenantNotificationOutboxEvent
): CustomPlanOfferReadyPayload {
  const payload = event.payload;
  const quoteId = payload.quoteId;
  const quoteName = payload.quoteName;
  const expiresAt = payload.expiresAt;

  if (
    typeof quoteId !== "string" ||
    !quoteId ||
    typeof quoteName !== "string" ||
    !quoteName ||
    !(expiresAt === null || typeof expiresAt === "string")
  ) {
    throw new Error(
      `Invalid CUSTOM_PLAN_OFFER_READY payload for outbox event ${event.id}`
    );
  }

  return {
    quoteId,
    quoteName,
    expiresAt
  };
}

export function buildTenantNotification(
  event: TenantNotificationOutboxEvent
): TenantNotificationDefinition {
  switch (event.event_type) {
    case "CUSTOM_PLAN_OFFER_READY": {
      const payload = readCustomPlanOfferReadyPayload(event);

      const notificationExpiresAt = payload.expiresAt
        ? new Date(payload.expiresAt)
        : null;

      if (
        notificationExpiresAt &&
        Number.isNaN(notificationExpiresAt.getTime())
      ) {
        throw new Error(
          `Invalid CUSTOM_PLAN_OFFER_READY expiry for outbox event ${event.id}`
        );
      }

      return {
        severity: "INFO",
        titleKey: "tenantNotifications.customPlanOfferReady.title",
        bodyKey: "tenantNotifications.customPlanOfferReady.body",
        resourceType: "custom_plan_quote",
        resourceId: payload.quoteId,
        expiresAt: notificationExpiresAt,
        recipientPolicy: {
          requiredPermissions: ["manage_billing"],
          permissionMode: "ANY"
        },
        payload: {
          quoteId: payload.quoteId,
          quoteName: payload.quoteName,
          expiresAt: payload.expiresAt
        }
      };
    }

    default:
      throw new Error(
        `Unsupported tenant notification event: ${event.event_type}`
      );
  }
}

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
    case "TENANT_REGISTERED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid TENANT_REGISTERED resource");
      return {severity:"INFO",titleKey:"platformNotifications.tenantRegistered.title",bodyKey:"platformNotifications.tenantRegistered.body",
        resourceType:"company",resourceId,
        recipientPolicy:{requiredPermissions:["companies.read"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "IMPORT_FAILED": {
      const resourceId=event.tenant_id;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid IMPORT_FAILED resource");
      return {severity:"WARNING",titleKey:"platformNotifications.importFailed.title",bodyKey:"platformNotifications.importFailed.body",
        resourceType:"company",resourceId,
        recipientPolicy:{requiredPermissions:["companies.read"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "SUBSCRIPTION_CHANGED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid SUBSCRIPTION_CHANGED resource");
      return {severity:"INFO",titleKey:"platformNotifications.subscriptionChanged.title",bodyKey:"platformNotifications.subscriptionChanged.body",
        resourceType:"subscription",resourceId,
        recipientPolicy:{requiredPermissions:["billing.read"],permissionMode:"ANY"},payload:{resourceId}};
    }

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

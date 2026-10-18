import type {
  CustomPlanOfferReadyPayload,
  TenantNotificationOutboxEvent
} from "./tenant-notification.types.js";

export type TenantNotificationDefinition = {
  category?: "business" | "market" | "imports";
  requiredFeature?: string;
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
    case "BUSINESS_RECOMMENDATION_READY": {
      const resourceId=event.payload.recommendationId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid BUSINESS_RECOMMENDATION_READY resource");
      return {category:"business",requiredFeature:"business_recommendations",severity:"WARNING",titleKey:"tenantNotifications.businessRecommendation.title",bodyKey:"tenantNotifications.businessRecommendation.body",
        resourceType:"business_recommendation",resourceId,expiresAt:null,
        recipientPolicy:{requiredPermissions:["view_analytics", "manage_catalog"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "MARKET_ALERT_TRIGGERED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid MARKET_ALERT_TRIGGERED resource");
      return {category:"market",requiredFeature:"system_alerts",severity:"WARNING",titleKey:"tenantNotifications.marketAlert.title",bodyKey:"tenantNotifications.marketAlert.body",
        resourceType:"market_alert",resourceId,expiresAt:null,
        recipientPolicy:{requiredPermissions:["view_analytics", "manage_catalog"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "IMPORT_COMPLETED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid IMPORT_COMPLETED resource");
      return {category:"imports",severity:"INFO",titleKey:"tenantNotifications.importCompleted.title",bodyKey:"tenantNotifications.importCompleted.body",
        resourceType:"ingestion_job",resourceId,expiresAt:null,
        recipientPolicy:{requiredPermissions:["manage_catalog"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "IMPORT_FAILED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid IMPORT_FAILED resource");
      return {category:"imports",severity:"WARNING",titleKey:"tenantNotifications.importFailed.title",bodyKey:"tenantNotifications.importFailed.body",
        resourceType:"ingestion_job",resourceId,expiresAt:null,
        recipientPolicy:{requiredPermissions:["manage_catalog"],permissionMode:"ANY"},payload:{resourceId}};
    }
    case "SUBSCRIPTION_CHANGED": {
      const resourceId=event.payload.resourceId;
      if(typeof resourceId!=="string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(resourceId))throw new Error("Invalid SUBSCRIPTION_CHANGED resource");
      return {severity:"INFO",titleKey:"tenantNotifications.subscriptionChanged.title",bodyKey:"tenantNotifications.subscriptionChanged.body",
        resourceType:"subscription",resourceId,expiresAt:null,
        recipientPolicy:{requiredPermissions:["manage_billing"],permissionMode:"ANY"},payload:{resourceId}};
    }

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

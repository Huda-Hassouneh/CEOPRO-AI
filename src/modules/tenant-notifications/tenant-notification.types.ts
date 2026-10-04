export const TENANT_NOTIFICATION_EVENTS = {
  CUSTOM_PLAN_OFFER_READY: "CUSTOM_PLAN_OFFER_READY"
} as const;

export type TenantNotificationEventType =
  (typeof TENANT_NOTIFICATION_EVENTS)[keyof typeof TENANT_NOTIFICATION_EVENTS];

export type TenantNotificationOutboxEvent = {
  id: string;
  tenant_id: string;
  event_type: string;
  dedupe_key: string;
  payload: Record<string, unknown>;
  status: "pending" | "processing" | "delivered" | "failed";
  attempts: number;
  occurred_at: Date;
  next_attempt_at: Date;
  delivered_at: Date | null;
  last_error_code: string | null;
  created_at: Date;
};

export type CustomPlanOfferReadyPayload = {
  quoteId: string;
  quoteName: string;
  expiresAt: string | null;
};

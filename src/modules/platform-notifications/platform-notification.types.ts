export const PLATFORM_NOTIFICATION_EVENTS = {
  PAYMENT_FAILED: "PAYMENT_FAILED"
} as const;

export type PlatformNotificationEventType =
  (typeof PLATFORM_NOTIFICATION_EVENTS)[keyof typeof PLATFORM_NOTIFICATION_EVENTS];

export type PlatformNotificationOutboxEvent = {
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

export type PaymentFailedPayload = {
  subscriptionId: string;
  stripeEventId: string;
  stripeInvoiceId: string;
  paymentIntentId: string | null;
  failureReason: string;
};

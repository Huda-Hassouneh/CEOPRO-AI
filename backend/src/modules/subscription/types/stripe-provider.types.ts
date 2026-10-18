import Stripe from "stripe";

export interface StripePriceDetails {
  name: string;
  description?: string;
  unitAmount: number; // major units, e.g. 29.99
  currency: string; // "usd"
  interval: "day" | "week" | "month" | "year";
  intervalCount?: number;
  trialPeriodDays?: number;
  idempotencyKey?: string;
}

export interface StripeCustomerDetails {
  email: string;
  name?: string;
  userId?: string;
  tenantId?: string;
}

export interface StripeSubscriptionDetails {
  customerId: string;
  priceId: string;
  trialPeriodDays?: number;
}

export interface StripeCheckoutDetails {
  priceId: string;
  customerId?: string;
  customerEmail?: string;
  successUrl: string; // must include {CHECKOUT_SESSION_ID}
  cancelUrl: string;
  trialPeriodDays?: number;
  couponId?: string;
  tenantId: string;
  newPlanId?: string;
}

export type StripeSubscriptionUpdateOutcome =
  | "applied"
  | "action_required"
  | "pending"
  | "scheduled"
  | "failed";

export interface StripeSubscriptionUpdateResult {
  subscription: Stripe.Subscription;
  outcome: StripeSubscriptionUpdateOutcome;
  latestInvoice: {
    id: string;
    status: string | null;
    hostedInvoiceUrl: string | null;
    paymentIntentStatus: string | null;
  } | null;
}

export interface StripeSubscriptionRecoverySnapshot {
  subscriptionId: string;
  customerId: string | null;
  status: string;
  tenantId: string | null;
  latestInvoice: {
    id: string;
    status: string | null;
    hostedInvoiceUrl: string | null;
  } | null;
}

export interface StripeService {
  createCatalog(payload?: {
    name: string;
    description: string;
  }): Promise<Stripe.Product>;
  createPlan(
    productId: string,
    planDetails: StripePriceDetails
  ): Promise<Stripe.Price>;
  stripeOnBoarding(): Promise<Stripe.Product>;
  createCustomer(details: StripeCustomerDetails): Promise<Stripe.Customer>;
  createSubscription(
    details: StripeSubscriptionDetails
  ): Promise<Stripe.Subscription>;
  createCheckoutSession(
    details: StripeCheckoutDetails
  ): Promise<Stripe.Checkout.Session>;
  createPromoCode(
    type: string,
    amount: number,
    discountAppliedFor?: string,
    currency?: string
  ): Promise<Stripe.Coupon>;
  retrievePromoCode(couponId: string): Promise<Stripe.Coupon>;
  stripe: Stripe;
  updateSubscription(data: {
    paymentProviderSubscriptionId: string;
    stripeSubscriptionItemId: string;
    paymentProviderPriceId: string;
    action: "upgrade" | "downgrade";
  }): Promise<StripeSubscriptionUpdateResult>;
  retrieveSubscription(subscriptionId: string): Promise<Stripe.Subscription>;
  retrieveSubscriptionForRecovery(
    subscriptionId: string
  ): Promise<StripeSubscriptionRecoverySnapshot>;
  updateSubscriptionCancellation(
    subscriptionId: string,
    cancelAtPeriodEnds: boolean,
    deleteImmedietly: boolean
  ): Promise<Stripe.Subscription>;
  deleteCustomerByCustomerId(customerId: string): Promise<boolean>;
  createCustomerPortalSession(
    customerId: string,
    returnUrl: string
  ): Promise<string>;
  releaseSubscriptionSchedule(
    subscriptionId: string
  ): Promise<Stripe.Subscription>;
}

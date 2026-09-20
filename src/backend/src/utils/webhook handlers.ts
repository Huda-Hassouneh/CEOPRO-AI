import Stripe from "stripe";
import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";
import subscriptionRepo from "../modules/subscription/repo/subscription.repo.js";
import webhookRepo from "../modules/subscription/repo/webhook.repo.js";
import {
  extractPaymentIntentId,
  extractSubscriptionId,
  insertSubscriptionWrapper
} from "./webhook.js";
import { consumePromocode } from "../modules/subscription/repo/promocodes.repo.js";
import { mapStripeSubscriptionStatus } from "../modules/subscription/External Services/Payment providers/stripe/webhook.service.js";
import plansRepo from "../modules/subscription/repo/plans.repo.js";

export async function handleCheckoutSessionCompleted(
  session: Stripe.Checkout.Session
) {
  const tenantId = session.metadata?.tenantId;

  if (!tenantId) {
    console.warn(
      `[Stripe] Ignored checkout.session.completed - Missing tenantId (Old test event)`
    );
    return;
  }

  console.log({ WEBHOOK: tenantId });

  if (!session.subscription) {
    console.warn(
      `[Audit] Checkout session ${session.id} finished without subscription ID`
    );
    return;
  }

  const stripeSubId =
    typeof session.subscription === "string"
      ? session.subscription
      : session.subscription.id;

  const existingSub =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(stripeSubId);

  if (!existingSub) {
    await insertSubscriptionWrapper(stripeSubId, tenantId);
  }
}

export async function handleSubscriptionUpdated(
  subscription: Stripe.Subscription
) {
  const currentSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(subscription.id);

  if (!currentSubscription) {
    throw new Error(
      `Subscription not found for paymentProviderSubscriptionId: ${subscription.id}`
    );
  }

  const item = subscription.items.data[0];
  if (!item) {
    throw new Error(
      `No items found in Stripe subscription: ${subscription.id}`
    );
  }

  const plan = await plansRepo.getPlanByPriceId(item.price.id);
  if (!plan) {
    throw new Error(`Plan not found for Stripe Price: ${item.price.id}`);
  }

  const billingOptions = (plan.billingOptions as any[]) || [];
  const matchedOption = billingOptions.find(
    (opt) => opt.stripePriceId === item.price.id
  );
  const billingPeriod = matchedOption?.period || "monthly";

  await subscriptionRepo.updateSubscription(currentSubscription.id, {
    planId: plan.id,
    paymentProviderPriceId: item.price.id,
    billingPeriod: billingPeriod,
    scheduledPlanId: null,
    scheduledBillingPeriod: null,
    status: mapStripeSubscriptionStatus(subscription.status),
    currentPeriodStart: new Date(item.current_period_start * 1000),
    currentPeriodEnd: new Date(item.current_period_end * 1000),
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
    cancelledAt: subscription.canceled_at
      ? new Date(subscription.canceled_at * 1000)
      : null
  });
}

export async function handleSubscriptionDeleted(
  stripeSubscription: Stripe.Subscription
) {
  const currentSubscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscription.id
    );

  if (!currentSubscription) {
    throw new Error(
      `Subscription not found for deletion: ${stripeSubscription.id}`
    );
  }

  await subscriptionRepo.updateSubscription(currentSubscription.id, {
    status: mapStripeSubscriptionStatus(stripeSubscription.status),
    cancelAtPeriodEnd: false,
    scheduledPlanId: null
  });
}

export async function handleInvoicePaid(invoice: Stripe.Invoice) {
  const tenantId = invoice.metadata?.tenantId;
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!tenantId) {
    console.warn(
      `[Stripe] Ignored invoice.paid - Missing tenantId (Old test event)`
    );
    return;
  }

  if (!stripeSubscriptionId) {
    console.warn(`[Audit] Invoice ${invoice.id} paid without subscription.`);
    return;
  }

  let subscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscriptionId
    );

  if (!subscription) {
    subscription = await insertSubscriptionWrapper(
      stripeSubscriptionId,
      tenantId
    );
  }

  await webhookRepo.createInvoicePayment(invoice, subscription.id, "succeeded");

  if (
    invoice.billing_reason === "subscription_create" &&
    invoice.discounts &&
    invoice.discounts.length > 0
  ) {
    const expandedInvoice = await stripeService.stripe.invoices.retrieve(
      invoice.id,
      {
        expand: ["discounts"]
      }
    );

    const discount = expandedInvoice.discounts[0] as any;
    let stripeCouponId: string | undefined = undefined;

    if (discount.source?.coupon) {
      stripeCouponId =
        typeof discount.source.coupon === "string"
          ? discount.source.coupon
          : discount.source.coupon.id;
    } else if (discount.coupon) {
      stripeCouponId =
        typeof discount.coupon === "string"
          ? discount.coupon
          : discount.coupon.id;
    }

    const rawSubscription =
      expandedInvoice.parent?.subscription_details?.subscription;
    const expandedStripeSubId =
      typeof rawSubscription === "string"
        ? rawSubscription
        : rawSubscription?.id;

    if (stripeCouponId && expandedStripeSubId) {
      await consumePromocode(expandedStripeSubId, stripeCouponId);
    }
  }
}

export async function handleInvoicePaymentFailed(invoice: Stripe.Invoice) {
  const tenantId = invoice.metadata?.tenantId;
  const stripeSubscriptionId = extractSubscriptionId(invoice);

  if (!tenantId) {
    console.warn(
      `[Stripe] Ignored invoice.payment_failed - Missing tenantId (Old test event)`
    );
    return;
  }

  if (!stripeSubscriptionId) {
    console.warn(
      `[Audit] Invoice ${invoice.id} payment failed without subscription.`
    );
    return;
  }

  let subscription =
    await subscriptionRepo.getSubscriptionByPaymentProviderId(
      stripeSubscriptionId
    );

  if (!subscription) {
    subscription = await insertSubscriptionWrapper(
      stripeSubscriptionId,
      tenantId
    );
  }

  await subscriptionRepo.updateSubscription(subscription.id, {
    status: "past_due"
  });

  let failureReason: string | null =
    invoice.last_finalization_error?.message ?? null;
  const paymentIntentId = extractPaymentIntentId(invoice);

  if (!failureReason && paymentIntentId) {
    try {
      const paymentIntent =
        await stripeService.stripe.paymentIntents.retrieve(paymentIntentId);
      failureReason =
        paymentIntent.last_payment_error?.message ??
        paymentIntent.last_payment_error?.decline_code ??
        null;
    } catch (err) {
      console.warn(
        `[Audit] Could not retrieve PaymentIntent ${paymentIntentId} for decline reason:`,
        err
      );
    }
  }

  if (!failureReason) {
    failureReason =
      "Payment collection failed (card declined or insufficient funds)";
  }

  await webhookRepo.createInvoicePayment(
    invoice,
    subscription.id,
    "failed",
    failureReason
  );
}

import Stripe from "stripe";
import { Plan, Subscription } from "../generated/prisma/client.js";
import { stripeService } from "../modules/subscription/External Services/Payment providers/stripe/stripeService.js";
import plansRepo from "../modules/subscription/repo/plans.repo.js";
import subscriptionRepo from "../modules/subscription/repo/subscription.repo.js";
import { mapStripeSubscriptionStatus } from "../modules/subscription/External Services/Payment providers/stripe/webhook.service.js";

export function extractSubscriptionId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as Record<string, any>;
  if (typeof inv.subscription_details?.subscription === "string")
    return inv.subscription_details.subscription;
  if (inv.subscription_details?.subscription?.id)
    return inv.subscription_details.subscription.id;
  if (typeof inv.parent?.subscription_details?.subscription === "string")
    return inv.parent.subscription_details.subscription;
  if (inv.parent?.subscription_details?.subscription?.id)
    return inv.parent.subscription_details.subscription.id;
  if (typeof inv.subscription === "string") return inv.subscription;
  if (inv.subscription?.id) return inv.subscription.id;
  return null;
}

export async function insertSubscriptionWrapper(
  subscriptionId: string,
  targetTenantId: string
): Promise<Subscription> {
  const subscription =
    await stripeService.stripe.subscriptions.retrieve(subscriptionId);
  const item = subscription.items.data[0];

  if (!item)
    throw new Error(`Stripe subscription ${subscriptionId} has no items`);

  const priceId = item.price.id;
  const plan = (await plansRepo.getPlanByPriceId(priceId)) as Plan;

  if (!plan)
    throw new Error(`Local plan not found for Stripe Price ID: ${priceId}`);

  const billingOptions = (plan.billingOptions as any[]) || [];
  const matchedOption = billingOptions.find(
    (opt) => opt.stripePriceId === priceId
  );
  const billingPeriod = matchedOption?.period || "monthly";

  return await subscriptionRepo.createSubscription({
    tenantId: targetTenantId,
    plan: { connect: { id: plan.id } },
    paymentProvider: "stripe",
    paymentProviderCustomerId: subscription.customer as string,
    paymentProviderSubscriptionId: subscription.id,
    paymentProviderPriceId: priceId,
    billingPeriod: billingPeriod,
    currentPeriodStart: new Date(item.current_period_start * 1000),
    currentPeriodEnd: new Date(item.current_period_end * 1000),
    status: mapStripeSubscriptionStatus(subscription.status),
    cancelAtPeriodEnd: subscription.cancel_at_period_end,
    cancelledAt: subscription.canceled_at
      ? new Date(subscription.canceled_at * 1000)
      : null
  });
}

export function extractPaymentIntentId(invoice: Stripe.Invoice): string | null {
  const inv = invoice as Record<string, any>;
  if (typeof inv.payment_intent === "string") return inv.payment_intent;
  if (inv.payment_intent?.id) return inv.payment_intent.id;
  if (typeof inv.payments?.data?.[0]?.payment_intent === "string")
    return inv.payments.data[0].payment_intent;
  return null;
}

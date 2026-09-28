/**
 * After migrating existing installations, read historical terms from Stripe.
 * This script is read-only against Stripe and only fills unknown local terms.
 * Run with the Stripe key for the same environment as this database.
 */
import { prisma } from "../src/config/database.js";
import { stripe } from "../src/modules/subscription/External Services/Payment providers/stripe/stripeService.js";
import { fromStripeMinorUnits } from "../src/utils/currency.js";

async function main() {
  const pending = await prisma.planPriceVersion.findMany({
    where: { OR: [{ amount: null }, { intervalUnit: null }, { intervalCount: null }] }
  });
  let skippedFixtures = 0;
  for (const version of pending) {
    if (!version.stripePriceId.startsWith("price_")) {
      skippedFixtures++;
      continue;
    }
    const price = await stripe.prices.retrieve(version.stripePriceId);
    if (price.type !== "recurring" || !price.recurring || price.unit_amount == null) {
      throw new Error(`Price ${version.stripePriceId} is not a supported fixed recurring price`);
    }
    await prisma.planPriceVersion.update({
      where: { id: version.id },
      data: {
        intervalUnit: price.recurring.interval,
        intervalCount: price.recurring.interval_count,
        amount: fromStripeMinorUnits(price.unit_amount, price.currency),
        currency: price.currency.toUpperCase()
      }
    });
  }
  console.log(`Reconciled ${pending.length - skippedFixtures} historical Stripe Prices; skipped ${skippedFixtures} non-Stripe fixtures.`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
}).finally(async () => prisma.$disconnect());

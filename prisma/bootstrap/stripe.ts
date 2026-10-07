import "dotenv/config";

import { onBoardingService } from "../../src/modules/subscription/service/onboarding.service.js";
import { getAppConfig } from "../../src/modules/subscription/repo/app-config.repo.js";
import { configKeys } from "../../src/config/keys.config.js";
import { prisma } from "../../src/config/database.js";
import { assertSafeStripeBootstrapEnvironment } from "./helpers/stripe.js";
import { line } from "./helpers/logs.js";

async function main() {
  assertSafeStripeBootstrapEnvironment();
  console.log("");
  line();
  console.log("Stripe Bootstrap");
  line();
  const key = configKeys.stripeAppConfigKey;

  /*
   * First check whether the Stripe product has already
   * been initialized.
   */
  const existingConfig = await getAppConfig(key);

  if (existingConfig?.value) {
    console.log("Stripe is already initialized.");
    console.log(`${key}: ${existingConfig.value}`);
    console.log("");
    console.log("Nothing to do.");

    return;
  }

  console.log("Stripe product is not initialized.");
  console.log("Creating shared CEOPRO Stripe product...");

  /*
   * Reuse the EXACT same service used by:
   *
   * POST /subscription
   *
   * That service:
   *
   * 1. Checks AppConfig
   * 2. Calls stripeService.stripeOnBoarding()
   * 3. Creates the Stripe Product
   * 4. Stores product.id as STRIPE_PRODUCT_ID
   */
  const result = await onBoardingService();

  if (!result.success) {
    throw new Error(
      `Stripe bootstrap failed with service code: ${result.code}`
    );
  }

  /*
   * Read it back from DB so we can verify that the
   * product ID was actually persisted.
   */
  const createdConfig = await getAppConfig(key);

  if (!createdConfig?.value) {
    throw new Error(
      "Stripe product was created but STRIPE_PRODUCT_ID was not found in AppConfig."
    );
  }

  console.log("");
  console.log("Stripe initialized successfully.");
  console.log(`${key}: ${createdConfig.value}`);

  console.log("");
  line();
}
main()
  .catch((error) => {
    console.error("");
    console.error("Stripe bootstrap failed:");
    console.error(error);

    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

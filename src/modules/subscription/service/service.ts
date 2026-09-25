import { ERROR_CODES } from "../../../errors/error-codes.js";
import { insertAppConfig, getAppConfig } from "../repo/repo.js";
import { configKeys } from "../../../config/keys.config.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";

import type { ServiceResult } from "../../../types/service.js";

export async function onBoardingService(): Promise<ServiceResult<null>> {
  // 1. Fail Fast: Check existence FIRST to prevent unnecessary Stripe API calls
  const isKeyExists = await getAppConfig(configKeys.stripeAppConfigKey);

  if (isKeyExists) {
    return { success: false, code: ERROR_CODES.RESOURCE_ALREADY_EXISTS };
  }

  // 2. Perform external integration and DB insert
  try {
    const result = await stripeService.stripeOnBoarding();
    await insertAppConfig(configKeys.stripeAppConfigKey, result.id);

    return { success: true, data: null };
  } catch (err) {
    console.error("Stripe Onboarding Error:", err);
    return { success: false, code: ERROR_CODES.EXTERNAL_SERVICE_ERROR };
  }
}

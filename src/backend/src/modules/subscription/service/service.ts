import { ERROR_CODES } from "../../../errors/error-codes.js";
import { ERROR_DEFINITIONS } from "../../../errors/error-defentions.js";
import { insertAppConfig, getAppConfig } from "../repo/repo.js";

import { ErrorResponse, SuccessResponse } from "../../../types/response.js";

import { configKeys } from "../../../config/keys.config.js";
import { stripeService } from "../External Services/Payment providers/stripe/stripeService.js";

export async function onBoardingService(): Promise<
  SuccessResponse<null> | ErrorResponse
> {
  try {
    const result = await stripeService.stripeOnBoarding();

    const isKeyExists = await getAppConfig(configKeys.stripeAppConfigKey);
    if (isKeyExists) {
      return {
        success: false,
        error: {
          code: ERROR_CODES.RESOURCE_ALREADY_EXISTS,
          message:
            ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].message,
          statusCode:
            ERROR_DEFINITIONS[ERROR_CODES.RESOURCE_ALREADY_EXISTS].statusCode
        }
      };
    }
    await insertAppConfig(configKeys.stripeAppConfigKey, result.id);
    return {
      success: true,
      data: null,
      message: `${configKeys.stripeAppConfigKey} inserted successfully .`
    };
  } catch (err) {
    console.error(err);
    return {
      success: false,
      error: {
        code: ERROR_CODES.EXTERNAL_SERVICE_ERROR,
        message: ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR].message,
        statusCode:
          ERROR_DEFINITIONS[ERROR_CODES.EXTERNAL_SERVICE_ERROR].statusCode
      }
    };
  }
}

import { ERROR_CODES } from "./error-codes.js";

export type ERROR_DEFINITION_ITEM = {
  statusCode: number;
  message: string;
};
export const ERROR_DEFINITIONS = {
  [ERROR_CODES.INVALID_WEBHOOK_HEADER]: {
    statusCode: 400,
    message: "webhook signature is required"
  },
  [ERROR_CODES.SUBSCRIPTION_CANCELLATION_SCHEDULED]: {
    statusCode: 200,
    message:
      "Subscription will be canceled at the end of the current billing period."
  },
  [ERROR_CODES.PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND]: {
    statusCode: 400,
    message: "Payment provider subscription ID is missing."
  },
  [ERROR_CODES.SAME_PLAN]: {
    statusCode: 400,
    message: "Subscription is already on this plan"
  },
  [ERROR_CODES.SUBSCRIPTION_ALREADY_CANCELED]: {
    statusCode: 400,
    message: "Subscription is already scheduled for cancellation."
  },
  [ERROR_CODES.SUBSCRIPTION_NOT_CANCELED]: {
    statusCode: 400,
    message: "Subscription is already not scheduled for cancellation."
  },
  [ERROR_CODES.UNAUTHORIZED]: {
    statusCode: 401,
    message: "Authentication is required"
  },

  [ERROR_CODES.INVALID_AUTH_HEADER]: {
    statusCode: 401,
    message: "Invalid authorization header format"
  },

  [ERROR_CODES.INVALID_TOKEN]: {
    statusCode: 401,
    message: "Invalid authentication token"
  },

  [ERROR_CODES.TOKEN_EXPIRED]: {
    statusCode: 401,
    message: "Authentication token has expired"
  },

  [ERROR_CODES.INVALID_CREDENTIALS]: {
    statusCode: 401,
    message: "Invalid email or password"
  },

  [ERROR_CODES.FORBIDDEN]: {
    statusCode: 403,
    message: "You do not have permission to perform this action"
  },

  [ERROR_CODES.INSUFFICIENT_PERMISSIONS]: {
    statusCode: 403,
    message: "Insufficient permissions"
  },

  [ERROR_CODES.TENANT_ACCESS_DENIED]: {
    statusCode: 403,
    message: "You do not have access to this tenant"
  },

  [ERROR_CODES.INVALID_REQUEST]: {
    statusCode: 400,
    message: "Invalid request"
  },

  [ERROR_CODES.VALIDATION_ERROR]: {
    statusCode: 400,
    message: "Validation failed"
  },

  [ERROR_CODES.INVALID_PARAMETER]: {
    statusCode: 400,
    message: "Invalid parameter"
  },

  [ERROR_CODES.UNPROCESSABLE_ENTITY]: {
    statusCode: 422,
    message: "The request could not be processed"
  },

  [ERROR_CODES.RESOURCE_NOT_FOUND]: {
    statusCode: 404,
    message: "Resource not found"
  },

  [ERROR_CODES.USER_NOT_FOUND]: {
    statusCode: 404,
    message: "User not found"
  },

  [ERROR_CODES.TENANT_NOT_FOUND]: {
    statusCode: 404,
    message: "Tenant not found"
  },

  [ERROR_CODES.PLAN_NOT_FOUND]: {
    statusCode: 404,
    message: "Subscription plan not found"
  },
  [ERROR_CODES.CUSTOM_PLAN_QUOTE_NOT_FOUND]: {
    statusCode: 404,
    message: "Custom plan quote not found"
  },
  [ERROR_CODES.VENDOR_RATE_NOT_FOUND]: {
    statusCode: 404,
    message: "Vendor rate not found"
  },

  [ERROR_CODES.SUBSCRIPTION_NOT_FOUND]: {
    statusCode: 404,
    message: "Subscription not found"
  },

  [ERROR_CODES.PROMO_CODE_NOT_FOUND]: {
    statusCode: 404,
    message: "Promo code not found"
  },

  [ERROR_CODES.RESOURCE_ALREADY_EXISTS]: {
    statusCode: 409,
    message: "Resource already exists"
  },

  [ERROR_CODES.USER_ALREADY_EXISTS]: {
    statusCode: 409,
    message: "User already exists"
  },

  [ERROR_CODES.TENANT_ALREADY_EXISTS]: {
    statusCode: 409,
    message: "Tenant already exists"
  },

  [ERROR_CODES.SUBSCRIPTION_ALREADY_EXISTS]: {
    statusCode: 409,
    message: "Subscription already exists"
  },

  [ERROR_CODES.INVALID_SUBSCRIPTION_STATUS]: {
    statusCode: 422,
    message: "Invalid subscription status"
  },

  [ERROR_CODES.SUBSCRIPTION_NOT_ACTIVE]: {
    statusCode: 422,
    message: "Subscription is not active"
  },

  [ERROR_CODES.PLAN_NOT_AVAILABLE]: {
    statusCode: 422,
    message: "The selected subscription plan is not available"
  },

  [ERROR_CODES.INVALID_PROMO_CODE]: {
    statusCode: 422,
    message: "Invalid promo code"
  },

  [ERROR_CODES.PROMO_CODE_EXPIRED]: {
    statusCode: 422,
    message: "Promo code has expired"
  },

  [ERROR_CODES.PROMO_CODE_NOT_ACTIVE]: {
    statusCode: 422,
    message: "Promo code is not active"
  },

  [ERROR_CODES.PROMO_CODE_USAGE_LIMIT_REACHED]: {
    statusCode: 422,
    message: "Promo code usage limit has been reached"
  },

  [ERROR_CODES.PROMO_CODE_NOT_APPLICABLE]: {
    statusCode: 422,
    message: "Promo code is not applicable"
  },

  [ERROR_CODES.PROMO_CODE_CURRENCY_MISMATCH]: {
    statusCode: 422,
    message: "Promo code currency does not match the selected plan currency"
  },

  [ERROR_CODES.UNSUPPORTED_PAYMENT_PROVIDER]: {
    statusCode: 422,
    message: "Unsupported payment provider"
  },

  [ERROR_CODES.PAYMENT_FAILED]: {
    statusCode: 402,
    message: "Payment failed"
  },

  [ERROR_CODES.PAYMENT_REQUIRED]: {
    statusCode: 402,
    message: "Payment is required"
  },

  [ERROR_CODES.PAYMENT_NOT_FOUND]: {
    statusCode: 404,
    message: "Payment not found"
  },

  [ERROR_CODES.EXTERNAL_SERVICE_ERROR]: {
    statusCode: 502,
    message: "External service error"
  },

  [ERROR_CODES.PAYMENT_PROVIDER_ERROR]: {
    statusCode: 502,
    message: "Payment provider error"
  },

  [ERROR_CODES.WEBHOOK_PROCESSING_ERROR]: {
    statusCode: 500,
    message: "Webhook processing failed"
  },

  [ERROR_CODES.INTERNAL_SERVER_ERROR]: {
    statusCode: 500,
    message: "An unexpected error occurred"
  },

  [ERROR_CODES.SERVICE_UNAVAILABLE]: {
    statusCode: 503,
    message: "Service is temporarily unavailable"
  },
  [ERROR_CODES.ALREADY_ACTIVE_PLAN]: {
    statusCode: 400,
    message:
      "You are currently actively subscribed to this plan and billing cycle."
  },
  [ERROR_CODES.ALREADY_SCHEDULED_PLAN]: {
    statusCode: 400,
    message:
      "You are already scheduled to transition to this plan and billing cycle at the end of your current term."
  },
  [ERROR_CODES.CANCEL_DOWNGRADE_REQUIRED]: {
    statusCode: 400,
    message:
      "You are already on this plan, but have a downgrade scheduled. Please cancel the pending downgrade to remain on this plan."
  },
  [ERROR_CODES.INVALID_BILLING_PERIOD]: {
    statusCode: 400,
    message: "The requested billing period is not valid for this plan."
  },
  [ERROR_CODES.INVALID_QUOTE_STATUS]: {
    statusCode: 409,
    message: "The custom plan quote is not in a valid state for this action."
  },
  [ERROR_CODES.UNSAFE_CUSTOM_PLAN_PRICE]: {
    statusCode: 422,
    message:
      "The final custom plan price is below the calculated minimum safe price."
  },
  [ERROR_CODES.FX_RATE_REQUIRED]: {
    statusCode: 422,
    message:
      "A valid FX rate is required to normalize vendor costs into the quote currency."
  },
  [ERROR_CODES.VENDOR_RATE_REQUIRED]: {
    statusCode: 422,
    message:
      "A vendor rate is required for each selected feature with estimated billable usage."
  },

  // AI & Data Extraction Errors
  [ERROR_CODES.MALFORMED_HISTORY_JSON]: {
    statusCode: 422, //[cite: 3]
    message: "Malformed history_json" //[cite: 3]
  },
  [ERROR_CODES.UPSTREAM_LLM_FAILURE]: {
    statusCode: 502, //[cite: 3]
    message: "Upstream language-model provider failure" //[cite: 3]
  },
  [ERROR_CODES.INVALID_FILE_UPLOAD]: {
    statusCode: 400, //[cite: 3]
    message: "Empty file, or file content does not match its extension" //[cite: 3]
  },
  [ERROR_CODES.FILE_SIZE_LIMIT_EXCEEDED]: {
    statusCode: 413, //[cite: 3]
    message: "File exceeds the size limit" //[cite: 3]
  }
} as const;

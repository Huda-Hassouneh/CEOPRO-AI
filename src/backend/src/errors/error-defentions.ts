import { ERROR_CODES } from "./error-codes.js";

export type ERROR_DEFINITION_ITEM = {
  statusCode: number;
  message: string;
};
export const ERROR_DEFINITIONS = {
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

  [ERROR_CODES.INTERNAL_SERVER_ERROR]: {
    statusCode: 500,
    message: "An unexpected error occurred"
  },

  [ERROR_CODES.SERVICE_UNAVAILABLE]: {
    statusCode: 503,
    message: "Service is temporarily unavailable"
  }
} as const;

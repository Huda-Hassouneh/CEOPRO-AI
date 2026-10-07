const CODE_KEYS = Object.freeze({
  UNAUTHORIZED: 'UNAUTHORIZED', INVALID_AUTH_HEADER: 'INVALID_AUTH_HEADER',
  INVALID_TOKEN: 'INVALID_TOKEN', TOKEN_EXPIRED: 'TOKEN_EXPIRED',
  INVALID_CREDENTIALS: 'INVALID_CREDENTIALS', EMAIL_VERIFICATION_INVALID: 'EMAIL_VERIFICATION_INVALID',
  EMAIL_DELIVERY_FAILED: 'EMAIL_DELIVERY_FAILED', FORBIDDEN: 'FORBIDDEN',
  INSUFFICIENT_PERMISSIONS: 'INSUFFICIENT_PERMISSIONS', TENANT_ACCESS_DENIED: 'TENANT_ACCESS_DENIED',
  INVALID_REQUEST: 'INVALID_REQUEST', VALIDATION_ERROR: 'VALIDATION_ERROR',
  INVALID_TEMPLATE: 'INVALID_TEMPLATE', INVALID_PARAMETER: 'INVALID_PARAMETER',
  UNPROCESSABLE_ENTITY: 'UNPROCESSABLE_ENTITY', PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND: 'PAYMENT_PROVIDER_SUBSCRIPTION_NOT_FOUND',
  RESOURCE_NOT_FOUND: 'RESOURCE_NOT_FOUND', USER_NOT_FOUND: 'USER_NOT_FOUND', TENANT_NOT_FOUND: 'TENANT_NOT_FOUND',
  PLAN_NOT_FOUND: 'PLAN_NOT_FOUND', CUSTOM_PLAN_QUOTE_NOT_FOUND: 'CUSTOM_PLAN_QUOTE_NOT_FOUND',
  VENDOR_RATE_NOT_FOUND: 'VENDOR_RATE_NOT_FOUND', SUBSCRIPTION_NOT_FOUND: 'SUBSCRIPTION_NOT_FOUND',
  PROMO_CODE_NOT_FOUND: 'PROMO_CODE_NOT_FOUND', INFRASTRUCTURE_RATE_NOT_FOUND: 'INFRASTRUCTURE_RATE_NOT_FOUND',
  NO_SCHEDULED_PLAN_CHANGE: 'NO_SCHEDULED_PLAN_CHANGE', RESOURCE_ALREADY_EXISTS: 'RESOURCE_ALREADY_EXISTS',
  SUBSCRIPTION_ALREADY_CANCELED: 'SUBSCRIPTION_ALREADY_CANCELED',
  SUBSCRIPTION_CANCELLATION_SCHEDULED: 'SUBSCRIPTION_CANCELLATION_SCHEDULED',
  SUBSCRIPTION_NOT_CANCELED: 'SUBSCRIPTION_NOT_CANCELED', INVALID_WEBHOOK_HEADER: 'INVALID_WEBHOOK_HEADER',
  USER_ALREADY_EXISTS: 'USER_ALREADY_EXISTS', TENANT_ALREADY_EXISTS: 'TENANT_ALREADY_EXISTS',
  SUBSCRIPTION_ALREADY_EXISTS: 'SUBSCRIPTION_ALREADY_EXISTS', ONBOARDING_INCOMPLETE: 'ONBOARDING_INCOMPLETE',
  INVALID_SUBSCRIPTION_STATUS: 'INVALID_SUBSCRIPTION_STATUS', SUBSCRIPTION_NOT_ACTIVE: 'SUBSCRIPTION_NOT_ACTIVE',
  PLAN_NOT_AVAILABLE: 'PLAN_NOT_AVAILABLE', SAME_PLAN: 'SAME_PLAN', INVALID_PROMO_CODE: 'INVALID_PROMO_CODE',
  PROMO_CODE_EXPIRED: 'PROMO_CODE_EXPIRED', PROMO_CODE_NOT_ACTIVE: 'PROMO_CODE_NOT_ACTIVE',
  PROMO_CODE_USAGE_LIMIT_REACHED: 'PROMO_CODE_USAGE_LIMIT_REACHED', PROMO_CODE_NOT_APPLICABLE: 'PROMO_CODE_NOT_APPLICABLE',
  PROMO_CODE_CURRENCY_MISMATCH: 'PROMO_CODE_CURRENCY_MISMATCH', UNSUPPORTED_PAYMENT_PROVIDER: 'UNSUPPORTED_PAYMENT_PROVIDER',
  PAYMENT_FAILED: 'PAYMENT_FAILED', PAYMENT_REQUIRED: 'PAYMENT_REQUIRED', PAYMENT_NOT_FOUND: 'PAYMENT_NOT_FOUND',
  EXTERNAL_SERVICE_ERROR: 'EXTERNAL_SERVICE_ERROR', NOT_IMPLEMENTED: 'NOT_IMPLEMENTED',
  PAYMENT_PROVIDER_ERROR: 'PAYMENT_PROVIDER_ERROR', WEBHOOK_PROCESSING_ERROR: 'WEBHOOK_PROCESSING_ERROR',
  INTERNAL_SERVER_ERROR: 'INTERNAL_SERVER_ERROR', SERVICE_UNAVAILABLE: 'SERVICE_UNAVAILABLE',
  ALREADY_ACTIVE_PLAN: 'ALREADY_ACTIVE_PLAN', ALREADY_SCHEDULED_PLAN: 'ALREADY_SCHEDULED_PLAN',
  CANCEL_DOWNGRADE_REQUIRED: 'CANCEL_DOWNGRADE_REQUIRED', INVALID_BILLING_PERIOD: 'INVALID_BILLING_PERIOD',
  INVALID_QUOTE_STATUS: 'INVALID_QUOTE_STATUS', UNSAFE_CUSTOM_PLAN_PRICE: 'UNSAFE_CUSTOM_PLAN_PRICE',
  FX_RATE_REQUIRED: 'FX_RATE_REQUIRED', VENDOR_RATE_REQUIRED: 'VENDOR_RATE_REQUIRED',
  MALFORMED_HISTORY_JSON: 'MALFORMED_HISTORY_JSON', UPSTREAM_LLM_FAILURE: 'UPSTREAM_LLM_FAILURE',
  INVALID_FILE_UPLOAD: 'INVALID_FILE_UPLOAD', FILE_SIZE_LIMIT_EXCEEDED: 'FILE_SIZE_LIMIT_EXCEEDED',
  QUOTA_EXCEEDED: 'QUOTA_EXCEEDED', ENTITLEMENT_NOT_AVAILABLE: 'ENTITLEMENT_NOT_AVAILABLE',
  AI_PROCESSED_OVER_LIMIT: 'AI_PROCESSED_OVER_LIMIT'
});

export function getApiError(error) {
  const payload = error?.response?.data ?? error;
  const backend = payload?.error ?? payload;
  return {
    status: error?.response?.status ?? backend?.statusCode ?? payload?.statusCode ?? null,
    code: backend?.code ?? payload?.code ?? error?.code ?? null,
    message: backend?.message ?? payload?.message ?? null,
    details: backend?.details ?? payload?.details ?? null,
    payload
  };
}

export function getApiErrorMessage(error, t, { fallbackKey = 'apiErrors.GENERIC' } = {}) {
  const apiError = getApiError(error);
  const keyCode = CODE_KEYS[apiError.code];
  const message = typeof apiError.message === 'string' ? apiError.message.trim() : '';
  const genericMessages = new Set([
    'request failed', 'internal server error', 'an unexpected error occurred', 'external service error',
    'invalid request', 'validation failed', 'resource not found', 'user not found', 'tenant not found',
    'subscription plan not found', 'custom plan quote not found', 'vendor rate not found', 'subscription not found',
    'promo code not found', 'infrastrucuture rate not found', 'infrastructure rate not found',
    'payment failed', 'payment is required', 'unsupported payment provider', 'payment provider error',
    'the request could not be processed', 'invalid parameter', 'invalid subscription status', 'subscription is not active',
    'the selected subscription plan is not available', 'invalid promo code', 'promo code has expired',
    'promo code is not active', 'resource already exists', 'user already exists', 'tenant already exists',
    'subscription already exists', 'complete the previous onboarding steps first', 'this operation is not supported',
    'upstream language-model provider failure', 'malformed history_json', 'empty file, or file content does not match its extension',
    'file exceeds the size limit', 'invalid authorization header format', 'authentication is required',
    'you do not have permission to perform this action', 'insufficient permissions', 'you do not have access to this tenant',
    'authentication token has expired', 'invalid authentication token', 'this email verification link is invalid or expired. request a new one.',
    'we could not send the verification email. please try again shortly.', 'this subscription is already scheduled for cancellation.',
    'subscription will be canceled at the end of the current billing period.', 'subscription is already not scheduled for cancellation.',
    'webhook signature is required'
  ]);
  if (message && !genericMessages.has(message.toLowerCase())) return message;
  if (keyCode) return (t || ((key) => key))(`apiErrors.${keyCode}`);
  const translateMessage = t || ((key) => key);
  if (!apiError.status && error?.request) return translateMessage('apiErrors.NETWORK');
  if (apiError.status === 401) return translateMessage('apiErrors.UNAUTHORIZED');
  if (apiError.status === 403) return translateMessage('apiErrors.FORBIDDEN');
  if (apiError.status === 404) return translateMessage('apiErrors.RESOURCE_NOT_FOUND');
  if (apiError.status === 402) return translateMessage('apiErrors.PAYMENT_REQUIRED');
  if (apiError.status === 413) return translateMessage('apiErrors.FILE_SIZE_LIMIT_EXCEEDED');
  if (apiError.status === 429) return translateMessage('apiErrors.TOO_MANY_REQUESTS');
  if (apiError.status >= 500) return translateMessage('apiErrors.SERVICE_UNAVAILABLE');
  return translateMessage(fallbackKey);
}


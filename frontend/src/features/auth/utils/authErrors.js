const ERROR_CODE_TRANSLATIONS = Object.freeze({
  INVALID_CREDENTIALS: 'auth.errors.invalidCredentials',
  EMAIL_IN_USE: 'auth.errors.emailInUse',
  INVALID_CODE: 'auth.errors.invalidCode',
  CODE_EXPIRED: 'auth.errors.expiredCode',
  TOO_MANY_ATTEMPTS: 'auth.errors.tooManyAttempts',
  ACCOUNT_NOT_FOUND: 'auth.errors.accountNotFound',
  EMAIL_DELIVERY_FAILED: 'auth.errors.emailDeliveryFailed',
});

// A code email counts as sent only when the API says the provider accepted it
// (backend routers/auth.py: {"status": "sent"}); anything else is not a send.
export function codeEmailWasSent(response) {
  return response?.status === 'sent';
}

export function getAuthErrorTranslationKey(error, { unauthorizedKey, fallbackKey = 'auth.errors.generic' } = {}) {
  const response = error?.response;
  const code = response?.data?.code;

  if (code && ERROR_CODE_TRANSLATIONS[code]) return ERROR_CODE_TRANSLATIONS[code];
  if (!response) return 'auth.errors.network';
  if (response.status === 401 && unauthorizedKey) return unauthorizedKey;
  if (response.status === 429) return 'auth.errors.tooManyAttempts';
  if (response.status >= 500) return 'auth.errors.serverUnavailable';
  return fallbackKey;
}

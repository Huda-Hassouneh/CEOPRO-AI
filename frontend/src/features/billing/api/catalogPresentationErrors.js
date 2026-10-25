export function getApiError(error) {
  const detail = error?.response?.data?.detail;
  const message = typeof detail === 'string' ? detail : detail?.message;
  return { message: message || error?.message || 'The request could not be completed.' };
}

export function isForbiddenBillingError(error) {
  return Number(error?.response?.status) === 403;
}
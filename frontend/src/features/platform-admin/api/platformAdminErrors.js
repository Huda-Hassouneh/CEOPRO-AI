export function getApiErrorMessage(error, t = (key) => key) {
  const status = error?.response?.status ?? error?.status ?? error?.statusCode;
  const detail = error?.response?.data?.detail ?? error?.data?.detail ?? error?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
  if (status === 401) return t('authenticationRequired') || 'Your session has expired. Sign in again.';
  if (status === 403) return t('permissionDenied') || 'Your account does not have permission for this operation.';
  if (status === 503) return t('serviceUnavailable') || 'The platform service is temporarily unavailable.';
  return error?.message || t('error') || 'The request could not be completed.';
}

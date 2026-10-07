import { translate } from './i18n.js';
import { getApiError, getApiErrorMessage as resolveApiErrorMessage } from './apiErrorCore.js';

export { getApiError };

function readLocale() {
  try {
    return window.localStorage.getItem('ceopro_locale') || 'en';
  } catch {
    return 'en';
  }
}

export function getApiErrorMessage(error, t, options) {
  return resolveApiErrorMessage(error, t || ((key) => translate(readLocale(), key)), options);
}

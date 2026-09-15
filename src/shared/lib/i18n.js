import en from '../../assets/locales/en.json';
import ar from '../../assets/locales/ar.json';
import landingEn from '../../features/landing/locales/en.json';
import landingAr from '../../features/landing/locales/ar.json';
import { en as adminEn, ar as adminAr } from '../../features/platform-admin/locales/messages.js';

export const DEFAULT_LOCALE = 'en';
export const SUPPORTED_LOCALES = Object.freeze(['en', 'ar']);
export const translations = Object.freeze({ en: { ...en, landing: landingEn, platformAdmin: adminEn }, ar: { ...ar, landing: landingAr, platformAdmin: adminAr } });

export const getLocaleDirection = (locale) => locale === 'ar' ? 'rtl' : 'ltr';

const resolveKey = (source, key) => key
  .split('.')
  .reduce((value, segment) => value?.[segment], source);

const interpolate = (message, values) => String(message).replace(
  /\{\{(\w+)\}\}/g,
  (match, key) => values[key] ?? match,
);

export function translate(locale, key, values = {}) {
  const normalizedLocale = SUPPORTED_LOCALES.includes(locale) ? locale : DEFAULT_LOCALE;
  const message = resolveKey(translations[normalizedLocale], key)
    ?? resolveKey(translations[DEFAULT_LOCALE], key)
    ?? key;

  return interpolate(message, values);
}

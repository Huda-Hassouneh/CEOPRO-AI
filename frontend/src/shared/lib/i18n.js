import en from '../../assets/locales/en.json';
import landingEn from '../../features/landing/locales/en.json';

export const DEFAULT_LOCALE = 'en';
export const SUPPORTED_LOCALES = Object.freeze(['en', 'ar']);
// English is bundled: it is the default and the fallback for any missing key.
// Arabic (58 kB compressed) is its own chunk, loaded only for people who use it.
const translations = { en: { ...en, landing: landingEn } };
const loaders = {
  ar: () => Promise.all([import('../../assets/locales/ar.json'), import('../../features/landing/locales/ar.json')])
    .then(([ar, landingAr]) => ({ ...ar.default, landing: landingAr.default })),
};
const pending = {};

export const isLocaleLoaded = (locale) => Boolean(translations[locale]);

// Resolves once `locale`'s messages are available (at once for English).
export function loadLocale(locale) {
  if (isLocaleLoaded(locale) || !loaders[locale]) return Promise.resolve();
  pending[locale] ??= loaders[locale]().then((messages) => { translations[locale] = messages; })
    .finally(() => { delete pending[locale]; });
  return pending[locale];
}

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

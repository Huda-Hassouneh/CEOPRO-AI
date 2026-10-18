import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { configureHttpClientLanguage } from '../../shared/lib/httpClient.js';
import {
  DEFAULT_LOCALE,
  SUPPORTED_LOCALES,
  getLocaleDirection,
  translate,
} from '../../shared/lib/i18n.js';

const LOCALE_STORAGE_KEY = 'ceopro_locale';
const I18nContext = createContext(null);

const readInitialLocale = () => {
  if (typeof window === 'undefined') return DEFAULT_LOCALE;
  try {
    const storedLocale = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    return SUPPORTED_LOCALES.includes(storedLocale) ? storedLocale : DEFAULT_LOCALE;
  } catch {
    return DEFAULT_LOCALE;
  }
};

export function I18nProvider({ children }) {
  const [locale, setLocaleState] = useState(readInitialLocale);
  const dir = getLocaleDirection(locale);
  const queryClient = useQueryClient();
  const previousLocale = useRef(locale);

  // Every API call carries the interface language, so names come back in it.
  configureHttpClientLanguage(() => locale);

  useEffect(() => {
    // Data already loaded holds names in the previous language: refetch it.
    if (previousLocale.current !== locale) {
      previousLocale.current = locale;
      queryClient.invalidateQueries();
    }
  }, [locale, queryClient]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, locale);
    } catch {
      // Locale still applies for this session when storage is unavailable.
    }
    document.documentElement.lang = locale;
    document.documentElement.dir = dir;
  }, [dir, locale]);

  const value = useMemo(() => ({
    locale,
    dir,
    setLocale: (nextLocale) => {
      if (SUPPORTED_LOCALES.includes(nextLocale)) setLocaleState(nextLocale);
    },
    t: (key, values) => translate(locale, key, values),
    supportedLocales: SUPPORTED_LOCALES,
  }), [dir, locale]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used within I18nProvider');
  return context;
}

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

// Light is the KEEL default; dark is an explicit user choice remembered on
// this device. index.html applies the stored choice before first paint so
// there is no flash of the wrong theme.
export const THEME_STORAGE_KEY = 'apex_theme';
export const THEMES = ['light', 'dark'];
const META_COLORS = { light: '#e4e6ea', dark: '#1b1d22' };

const ThemeContext = createContext({ theme: 'light', setTheme: () => {}, toggleTheme: () => {} });

const readStoredTheme = () => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return THEMES.includes(stored) ? stored : 'light';
  } catch {
    return 'light';
  }
};

const applyTheme = (theme, animate) => {
  const root = document.documentElement;
  if (animate) {
    root.classList.add('apex-theme-switching');
    window.setTimeout(() => root.classList.remove('apex-theme-switching'), 450);
  }
  if (theme === 'dark') root.setAttribute('data-theme', 'dark');
  else root.removeAttribute('data-theme');
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', META_COLORS[theme]);
};

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(() => (typeof window === 'undefined' ? 'light' : readStoredTheme()));

  useEffect(() => { applyTheme(theme, false); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const setTheme = useCallback((next) => {
    if (!THEMES.includes(next)) return;
    setThemeState(next);
    applyTheme(next, true);
    try { window.localStorage.setItem(THEME_STORAGE_KEY, next); } catch { /* private mode: theme still applies for this visit */ }
  }, []);

  const toggleTheme = useCallback(() => setTheme(theme === 'dark' ? 'light' : 'dark'), [setTheme, theme]);
  const value = useMemo(() => ({ theme, setTheme, toggleTheme }), [theme, setTheme, toggleTheme]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);

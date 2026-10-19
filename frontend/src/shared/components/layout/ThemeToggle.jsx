import { Moon, Sun } from 'lucide-react';
import { useTheme } from '../../../app/providers/ThemeProvider.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

// Light <-> dark. The icon morphs between sun and moon.
export default function ThemeToggle({ className = '' }) {
  const { theme, toggleTheme } = useTheme();
  const { t } = useI18n();
  const dark = theme === 'dark';
  const label = dark ? t('businessShell.theme.switchToLight') : t('businessShell.theme.switchToDark');
  return (
    <button type="button" className={`apex-theme-toggle${dark ? ' is-dark' : ''} ${className}`.trim()} onClick={toggleTheme} aria-label={label} title={label} aria-pressed={dark}>
      <span className="apex-theme-toggle__track" aria-hidden="true">
        <span className="apex-theme-toggle__thumb">
          <Sun size={14} className="apex-theme-toggle__sun" />
          <Moon size={14} className="apex-theme-toggle__moon" />
        </span>
      </span>
    </button>
  );
}

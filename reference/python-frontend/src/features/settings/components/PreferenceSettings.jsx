import { Languages } from 'lucide-react';
import { SettingsSection } from './SettingsSection.jsx';

export function PreferenceSettings({ locale, setLocale, t }) {
  return <SettingsSection title={t('settings.preferences.title')} subtitle={t('settings.preferences.subtitle')}><fieldset className="settings-language-options"><legend><Languages size={18} />{t('settings.preferences.language')}</legend>{[{ value: 'en', label: 'English' }, { value: 'ar', label: 'العربية' }].map((option) => <label className={locale === option.value ? 'is-selected' : ''} key={option.value}><input type="radio" name="settings-language" value={option.value} checked={locale === option.value} onChange={() => setLocale(option.value)} /><span><strong>{option.label}</strong><small>{t(`settings.preferences.languages.${option.value}`)}</small></span></label>)}</fieldset><p className="settings-capability-note">{t('settings.preferences.languageDirection')}</p></SettingsSection>;
}

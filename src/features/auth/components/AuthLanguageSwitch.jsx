import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import '../styles/AuthForms.css';

export function AuthLanguageSwitch() {
  const { locale, setLocale, t } = useI18n();
  const languages = locale === 'ar'
    ? [{ code: 'ar', label: t('common.arabic') }, { code: 'en', label: t('common.englishShort') }]
    : [{ code: 'en', label: t('common.englishShort') }, { code: 'ar', label: t('common.arabic') }];

  return (
    <div className="ceopro-auth-language-switch" role="group" aria-label={t('common.languageSwitch')}>
      {languages.map((language, index) => (
        <span className="ceopro-auth-language-switch__item" key={language.code}>
          {index > 0 && <span className="ceopro-auth-language-switch__divider" aria-hidden="true">|</span>}
          <button
            type="button"
            className="ceopro-auth-language-switch__button"
            aria-pressed={locale === language.code}
            onClick={() => setLocale(language.code)}
          >
            {language.label}
          </button>
        </span>
      ))}
    </div>
  );
}

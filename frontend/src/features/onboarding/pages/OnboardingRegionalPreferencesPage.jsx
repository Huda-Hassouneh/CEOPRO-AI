import { useEffect } from 'react';
import { Info } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Select from '../../../shared/components/ui/Select.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';
import { ORANGE_COUNTRIES, getCitiesForCountry, isSupportedCountryCity } from '../config/countries.js';
import { applicationLanguages } from '../types/onboarding.types.js';

export function OnboardingRegionalPreferencesPage() {
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();
  const country = useOnboardingStore((state) => state.country);
  const city = useOnboardingStore((state) => state.city);
  const setRegionalPreferences = useOnboardingStore((state) => state.setRegionalPreferences);
  const completeStep = useOnboardingStore((state) => state.completeStep);
  const countryIsValid = ORANGE_COUNTRIES.some((item) => item.value === country);
  const cities = countryIsValid ? getCitiesForCountry(country) : [];
  const cityIsValid = isSupportedCountryCity(country, city);
  const languageIsValid = applicationLanguages.some((item) => item.value === locale);

  useEffect(() => {
    if (city && !cityIsValid) setRegionalPreferences({ city: '' });
  }, [city, cityIsValid, setRegionalPreferences]);

  const requiredLabel = (key) => <>{t(key)} <span className="ceopro-required-mark" aria-hidden="true">*</span></>;

  return (
    <OnboardingPageShell step={1} title={t('onboarding.region.title')} subtitle={t('onboarding.region.subtitle')} wide>
      <div className="ceopro-region-grid">
        <div className="ceopro-region-field">
          <label htmlFor="setup-country">{requiredLabel('onboarding.region.countryLabel')}</label>
          <small>{t('onboarding.region.countryHint')}</small>
          <Select
            id="setup-country"
            value={country}
            required
            aria-required="true"
            options={ORANGE_COUNTRIES.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
            onChange={(event) => setRegionalPreferences({ country: event.target.value, city: '' })}
          />
        </div>
        <div className="ceopro-region-field">
          <label htmlFor="setup-city">{requiredLabel('onboarding.region.cityLabel')}</label>
          <small>{t('onboarding.region.cityHint')}</small>
          <Select
            id="setup-city"
            value={cityIsValid ? city : ''}
            required
            aria-required="true"
            disabled={!countryIsValid}
            options={[
              { value: '', label: t('onboarding.region.cityPlaceholder') },
              ...cities.map((item) => ({ value: item.value, label: t(item.labelKey) })),
            ]}
            onChange={(event) => setRegionalPreferences({ city: event.target.value })}
          />
        </div>
        <div className="ceopro-region-field">
          <label htmlFor="setup-product-language">{requiredLabel('onboarding.region.languageLabel')}</label>
          <small>{t('onboarding.region.languageHint')}</small>
          <Select
            id="setup-product-language"
            value={locale}
            required
            aria-required="true"
            options={applicationLanguages.map((item) => ({ value: item.value, label: t(item.labelKey) }))}
            onChange={(event) => setLocale(event.target.value)}
          />
        </div>
      </div>
      <div className="ceopro-region-note"><Info size={18} aria-hidden="true" /><span><strong>{t('onboarding.region.noteMarket')}</strong><small>{t('onboarding.region.noteLanguage')}</small></span></div>
      <OnboardingActions
        onContinue={() => { completeStep(1); navigate(routePaths.onboardingIndustry); }}
        disabled={!countryIsValid || !cityIsValid || !languageIsValid}
      />
    </OnboardingPageShell>
  );
}

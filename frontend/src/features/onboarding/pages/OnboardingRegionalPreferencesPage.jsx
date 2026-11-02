import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Info } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Select from '../../../shared/components/ui/Select.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { countryOptions, COUNTRY_CODES } from '../../../shared/config/countries.js';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { OnboardingActions } from '../components/OnboardingActions.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';
import { cityOptions, filterCityOptions } from '../config/locationOptions.js';
import { applicationLanguages } from '../types/onboarding.types.js';

export function OnboardingRegionalPreferencesPage() {
  const navigate = useNavigate();
  const { locale, setLocale, t } = useI18n();
  const country = useOnboardingStore((state) => state.country);
  const city = useOnboardingStore((state) => state.city);
  const savedRegion = useOnboardingStore((state) => state.savedRegion);
  const [citySearch, setCitySearch] = useState('');
  const setRegionalPreferences = useOnboardingStore((state) => state.setRegionalPreferences);
  const completeStep = useOnboardingStore((state) => state.completeStep);
  const countryIsValid = COUNTRY_CODES.includes(country);
  const catalog = useQuery({
    queryKey: ['onboarding-cities', country],
    queryFn: async () => (await import('../config/loadCities.js')).loadCities(country),
    enabled: countryIsValid,
    staleTime: Infinity,
  });
  const cities = useMemo(
    () => countryIsValid ? cityOptions(country, catalog.data || [], locale, t, savedRegion) : [],
    [countryIsValid, country, catalog.data, locale, t, savedRegion],
  );
  const cityIsValid = cities.some((item) => item.value === city);
  const languageIsValid = applicationLanguages.some((item) => item.value === locale);

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
            options={[{value:'',label:t('onboarding.region.countryPlaceholder')},...countryOptions(locale)]}
            onChange={(event) => { setCitySearch(''); setRegionalPreferences({ country: event.target.value }); }}
          />
        </div>
        <div className="ceopro-region-field">
          <label htmlFor="setup-city">{requiredLabel('onboarding.region.cityLabel')}</label>
          <small>{t('onboarding.region.cityHint')}</small>
          <Input
            id="setup-city-search"
            aria-label={t('onboarding.region.citySearch')}
            placeholder={t('onboarding.region.citySearch')}
            value={citySearch}
            disabled={!countryIsValid || catalog.isPending || catalog.isError}
            onChange={(event)=>setCitySearch(event.target.value)}
          />
          <Select
            id="setup-city"
            value={cityIsValid ? city : ''}
            required
            aria-required="true"
            disabled={!countryIsValid || catalog.isPending || catalog.isError}
            options={[
              { value: '', label: t('onboarding.region.cityPlaceholder') },
              ...filterCityOptions(cities,citySearch,city),
            ]}
            onChange={(event) => setRegionalPreferences({ city: event.target.value })}
          />
          {countryIsValid && catalog.isPending && <small role="status">{t('common.loading')}</small>}
          {catalog.isError && <div role="alert">{t('onboarding.region.cityLoadError')} <Button onClick={()=>catalog.refetch()}>{t('billing.management.retry')}</Button></div>}
          {catalog.isSuccess && cities.length===0 && <small role="status">{t('onboarding.region.noCities')}</small>}
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
        onContinue={async () => { if (await completeStep(1)) navigate(routePaths.onboardingIndustry); }}
        disabled={!countryIsValid || !cityIsValid || !languageIsValid || catalog.isPending || catalog.isError}
      />
    </OnboardingPageShell>
  );
}

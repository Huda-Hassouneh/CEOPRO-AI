import { useEffect, useState } from 'react';
import { CreditCard } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { discoveryApi } from '../../market-intelligence/api/discoveryApi.js';
import { routePaths } from '../../../app/router/routePaths.js';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Select from '../../../shared/components/ui/Select.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { SettingsSection } from './SettingsSection.jsx';
import { TargetMarketsSettings } from './TargetMarketsSettings.jsx';
import { CompanyDataSettings } from './CompanyDataSettings.jsx';
import { useUpdateCompany } from '../hooks/useUpdateCompany.js';
import { countryOptions as allCountries } from '../../../shared/config/countries.js';

// The real backend/src/ai/routers/settings.py::update_company() is
// owner/admin-only server-side and already fully wired - companyApi.js's
// updateCompany()/getCompany() have carried this contract since before
// this form existed. This was the one settings tab still rendering a
// static read-only <dl> instead of using it, same gap ProfileForm.jsx
// and TargetMarketsSettings.jsx both already closed for their own data.
//
// businessSize is deliberately not a field here - companies has no such
// column (companyApi.js's toCompany() leaves it undefined on purpose), so
// an editable input for it would save nothing and silently lie about it.
const BLANK = { name: '', industry: '', country: '', currency: '', industryKey: '', description: '', website: '' };

export function CompanySettings({ query, permissions, t, onNotice }) {
  const navigate = useNavigate();
  const { locale } = useI18n();
  const mutation = useUpdateCompany();
  const industries = useQuery({ queryKey: ['industries'], queryFn: discoveryApi.industries, staleTime: Infinity });
  const [values, setValues] = useState(BLANK);
  const company = query.data?.company;
  useEffect(() => {
    if (company) {
      setValues(Object.fromEntries(Object.keys(BLANK).map((key) => [key, company[key] || ''])));
    }
  }, [company]);

  if (query.isPending) return <Skeleton height="310px" variant="rectangular" />;
  if (query.isError) return <SettingsSection title={t('settings.company.title')}><p className="settings-inline-error">{t('settings.company.loadError')}</p></SettingsSection>;

  const canEdit = permissions.canEditCompany && query.data.capabilities.updateCompany;
  const dirty = Boolean(company) && Object.keys(BLANK).some((key) => values[key] !== (company[key] || ''));
  const isArabic = locale?.startsWith('ar');
  const industryOptions = [{ value: '', label: t('settings.company.industryKeyPlaceholder') },
    ...(industries.data || []).map((item) => ({ value: item.key, label: isArabic ? item.label.ar : item.label.en }))];

  const save = async (event) => {
    event.preventDefault();
    if (!canEdit || mutation.isPending || !dirty || !values.name.trim()) return;
    try {
      await mutation.mutateAsync({ ...values, currency: values.currency.trim().toUpperCase() });
      onNotice?.('success', t('settings.company.saved'));
    } catch (err) {
      onNotice?.('error', err?.response?.data?.detail || t('settings.company.saveError'));
    }
  };

  const countryOptions = [{ value: '', label: t('settings.company.countryPlaceholder') }, ...allCountries(locale)];

  return <>
    <SettingsSection title={t('settings.company.title')} subtitle={t('settings.company.subtitle')} actions={permissions.canEditCompany && <Button size="sm" variant="outline" leadingIcon={<CreditCard size={14} />} onClick={() => navigate(routePaths.billing)}>{t('settings.company.manageSubscription')}</Button>}>
      <form className="settings-form" onSubmit={save}>
        <div className="settings-form-grid">
          <Input label={t('settings.company.fields.name')} value={values.name} readOnly={!canEdit} onChange={(event) => setValues({ ...values, name: event.target.value })} />
          <Input label={t('settings.company.fields.industry')} value={values.industry} readOnly={!canEdit} placeholder={t('settings.company.industryPlaceholder')} onChange={(event) => setValues({ ...values, industry: event.target.value })} />
          {canEdit
            ? <Select label={t('settings.company.fields.country')} value={values.country} onChange={(event) => setValues({ ...values, country: event.target.value })} options={countryOptions} />
            : <Input label={t('settings.company.fields.country')} value={values.country || t('settings.common.notAvailable')} readOnly />}
          <Input label={t('settings.company.fields.currency')} value={values.currency} readOnly={!canEdit} placeholder={t('settings.company.currencyPlaceholder')} maxLength={3} onChange={(event) => setValues({ ...values, currency: event.target.value.toUpperCase() })} />
          <Select label={t('settings.company.fields.industryKey')} hint={t('settings.company.industryKeyHint')} value={values.industryKey} disabled={!canEdit} onChange={(event) => setValues({ ...values, industryKey: event.target.value })} options={industryOptions} />
          <Input label={t('settings.company.fields.website')} value={values.website} readOnly={!canEdit} placeholder="example.com" dir="ltr" onChange={(event) => setValues({ ...values, website: event.target.value })} />
          <Input label={t('settings.company.fields.description')} value={values.description} readOnly={!canEdit} placeholder={t('settings.company.descriptionPlaceholder')} maxLength={1000} onChange={(event) => setValues({ ...values, description: event.target.value })} />
        </div>
        {!canEdit && <p className="settings-capability-note">{t(permissions.canEditCompany ? 'settings.company.editUnavailable' : 'settings.company.readOnly')}</p>}
        {canEdit && <div className="settings-form-actions"><Button type="submit" disabled={!dirty || !values.name.trim()} loading={mutation.isPending} loadingLabel={t('settings.common.saving')}>{t('settings.common.saveChanges')}</Button></div>}
      </form>
    </SettingsSection>
    <TargetMarketsSettings permissions={permissions} t={t} />
    <CompanyDataSettings permissions={permissions} companyName={company?.name} t={t} />
  </>;
}

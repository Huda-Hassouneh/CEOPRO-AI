import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Building2 } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Panel } from '../../../shared/components/apex/Apex.jsx';
import { countryOptions, currencyOptions, defaultCurrencyFor } from '../../../shared/config/countries.js';
import { workspacesApi } from '../api/workspacesApi.js';
import { useOpenWorkspace } from '../useOpenWorkspace.js';

// A new company under the same login: its own catalogue, sales, competitors,
// plan and team - nothing is copied from the current company.
export function CreateWorkspacePage() {
  const { t, locale } = useI18n();
  const navigate = useNavigate();
  const openWorkspace = useOpenWorkspace();
  const [values, setValues] = useState({ name: '', country: '', currency: '' });
  const [state, setState] = useState({ busy: false, error: null });
  const valid = values.name.trim() && values.country && values.currency;

  const setCountry = (country) => setValues((v) => ({
    ...v, country, currency: !v.currency || v.currency === defaultCurrencyFor(v.country) ? defaultCurrencyFor(country) : v.currency,
  }));

  const submit = async (event) => {
    event.preventDefault();
    if (!valid || state.busy) return;
    setState({ busy: true, error: null });
    try {
      const session = await workspacesApi.create({ name: values.name.trim(), country: values.country, currency: values.currency });
      openWorkspace(session);
    } catch (error) {
      const status = error?.response?.status;
      setState({ busy: false, error: status === 409 ? 'workspaces.create.tooMany' : 'workspaces.create.failed' });
    }
  };

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        <PageHeader title={t('workspaces.create.title')} subtitle={t('workspaces.create.subtitle')}
          actions={<ApexButton variant="ghost" icon={ArrowLeft} onClick={() => navigate(-1)}>{t('workspaces.create.back')}</ApexButton>} />
        <Panel className="workspace-create">
          <form className="setup-form" onSubmit={submit} noValidate>
            <label className="setup-field">
              <span>{t('workspaces.create.name')}</span>
              <input className="apex-input" value={values.name} maxLength={200} autoFocus placeholder={t('workspaces.create.namePlaceholder')} onChange={(e) => setValues({ ...values, name: e.target.value })} />
            </label>
            <div className="setup-row">
              <label className="setup-field">
                <span>{t('workspaces.create.country')}</span>
                <select className="apex-select" value={values.country} onChange={(e) => setCountry(e.target.value)}>
                  <option value="">{t('workspaces.create.countryPlaceholder')}</option>
                  {countryOptions(locale).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </label>
              <label className="setup-field">
                <span>{t('workspaces.create.currency')}</span>
                <select className="apex-select" value={values.currency} onChange={(e) => setValues({ ...values, currency: e.target.value })}>
                  <option value="">{t('workspaces.create.currencyPlaceholder')}</option>
                  {currencyOptions(locale).map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
                </select>
              </label>
            </div>
            <p className="apex-muted setup-note">{t('workspaces.create.note')}</p>
            {state.error && <p className="market-scan__note is-error" role="alert">{t(state.error)}</p>}
            <div className="setup-actions">
              <ApexButton type="submit" icon={Building2} loading={state.busy} disabled={!valid}>{t('workspaces.create.submit')}</ApexButton>
            </div>
          </form>
        </Panel>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

export default CreateWorkspacePage;

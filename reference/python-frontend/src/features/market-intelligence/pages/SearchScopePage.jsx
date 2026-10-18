import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Crosshair, MapPin, Save } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Panel, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useSearchScope } from '../hooks/useSearchScope.js';
import { useUpdateSearchScope } from '../hooks/useUpdateSearchScope.js';
import '../../onboarding/styles/Setup.css';

const RADII = [1, 2, 5, 10, 25, 50];

// Where the business is and how far its competition reaches - the area the
// market scan searches.
export function SearchScopePage() {
  const { t } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const scope = useSearchScope();
  const update = useUpdateSearchScope();
  const [values, setValues] = useState({ city: '', latitude: '', longitude: '', radius: 5 });
  const [notice, setNotice] = useState(null);
  const [locating, setLocating] = useState(false);

  useEffect(() => {
    const s = scope.data;
    if (s) setValues({ city: s.city || '', latitude: s.latitude ?? '', longitude: s.longitude ?? '', radius: s.default_search_radius_km || 5 });
  }, [scope.data]);

  const lat = values.latitude === '' ? null : Number(values.latitude);
  const lon = values.longitude === '' ? null : Number(values.longitude);
  const pinValid = (lat == null && lon == null) || (Number.isFinite(lat) && Number.isFinite(lon) && Math.abs(lat) <= 90 && Math.abs(lon) <= 180);
  const valid = pinValid && (values.city.trim() || lat != null) && values.radius >= 1 && values.radius <= 500;

  const locate = () => {
    if (!navigator.geolocation) { setNotice({ tone: 'error', key: 'setup.location.unsupported' }); return; }
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (p) => { setValues((v) => ({ ...v, latitude: p.coords.latitude.toFixed(6), longitude: p.coords.longitude.toFixed(6) })); setLocating(false); },
      () => { setNotice({ tone: 'error', key: 'setup.location.denied' }); setLocating(false); },
      { timeout: 15000 },
    );
  };

  const save = async (event) => {
    event.preventDefault();
    if (!valid) return;
    setNotice(null);
    try {
      await update.mutateAsync({
        city: values.city.trim() || undefined,
        ...(lat != null ? { latitude: lat, longitude: lon } : {}),
        searchScopeLevel: 'CUSTOM', customRadiusKm: Math.round(values.radius),
      });
      queryClient.invalidateQueries({ queryKey: ['discovery-status'] });
      setNotice({ tone: 'success', key: 'scopeArea.saved' });
    } catch {
      setNotice({ tone: 'error', key: 'scopeArea.saveError' });
    }
  };

  const header = <PageHeader title={t('scopeArea.title')} subtitle={t('scopeArea.subtitle')}
    actions={<ApexButton variant="ghost" icon={ArrowLeft} onClick={() => navigate(routePaths.market)}>{t('market.scope.back')}</ApexButton>} />;

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        {header}
        <Panel className="workspace-create">
          {scope.isPending ? <StateBlock kind="loading" title={t('common.loading')} />
            : scope.isError ? <StateBlock kind="error" title={t('market.scope.loadError')} onRetry={() => scope.refetch()} retryLabel={t('demandApex.actions.retry')} />
              : (
                <form className="setup-form" onSubmit={save} noValidate>
                  <label className="setup-field"><span>{t('setup.location.city')}</span>
                    <input className="apex-input" value={values.city} maxLength={150} placeholder={t('setup.location.cityPlaceholder')} onChange={(e) => setValues({ ...values, city: e.target.value })} /></label>
                  <div className="setup-locate">
                    <ApexButton variant="secondary" icon={Crosshair} loading={locating} onClick={locate}>{t('setup.location.useMine')}</ApexButton>
                  </div>
                  <div className="setup-row">
                    <label className="setup-field"><span>{t('scopeArea.latitude')}</span>
                      <input className="apex-input" dir="ltr" inputMode="decimal" value={values.latitude} placeholder="31.9539" onChange={(e) => setValues({ ...values, latitude: e.target.value.trim() })} /></label>
                    <label className="setup-field"><span>{t('scopeArea.longitude')}</span>
                      <input className="apex-input" dir="ltr" inputMode="decimal" value={values.longitude} placeholder="35.9106" onChange={(e) => setValues({ ...values, longitude: e.target.value.trim() })} /></label>
                  </div>
                  {!pinValid && <p className="market-scan__note is-error">{t('scopeArea.pinInvalid')}</p>}
                  <p className="apex-muted setup-note"><MapPin size={13} aria-hidden="true" /> {t('scopeArea.pinHint')}</p>
                  <fieldset className="setup-field">
                    <legend>{t('setup.location.radius')}</legend>
                    <div className="apex-segmented" role="group">
                      {RADII.map((r) => <button key={r} type="button" aria-pressed={Number(values.radius) === r} onClick={() => setValues({ ...values, radius: r })}>{t('discovery.list.km', { km: r })}</button>)}
                    </div>
                    <p className="apex-muted setup-note">{t('setup.location.radiusHint')}</p>
                  </fieldset>
                  {notice && <p className={`market-scan__note${notice.tone === 'error' ? ' is-error' : ''}`} role={notice.tone === 'error' ? 'alert' : 'status'}>{t(notice.key)}</p>}
                  <div className="setup-actions">
                    <ApexButton type="submit" icon={Save} loading={update.isPending} disabled={!valid}>{t('market.scope.save')}</ApexButton>
                  </div>
                </form>
              )}
        </Panel>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

export default SearchScopePage;

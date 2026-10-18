import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, Check, Crosshair, MapPin, Package, Plus, Radar, Store, Trash2 } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { ApexButton, Panel, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { countryName } from '../../../shared/config/countries.js';
import httpClient from '../../../shared/lib/httpClient.js';
import { companyApi } from '../../settings/api/companyApi.js';
import { productsApi } from '../../products/api/productsApi.js';
import { discoveryApi } from '../../market-intelligence/api/discoveryApi.js';
import '../styles/Setup.css';

const STEPS = ['business', 'location', 'products', 'finish'];
const RADII = [2, 5, 10, 25];
const ARABIC = /[؀-ۿ]/;

// Guided company setup: what the business is, where it is, a few products,
// then the first market scan. Every step saves to the real company profile,
// so leaving half-way keeps what was entered.
export function SetupPage() {
  const { t, locale, dir } = useI18n();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const isArabic = locale?.startsWith('ar');
  const company = useQuery({ queryKey: ['settings-company', 'setup'], queryFn: () => companyApi.getCompany() });
  const industries = useQuery({ queryKey: ['industries'], queryFn: discoveryApi.industries, staleTime: Infinity });
  const scope = useQuery({ queryKey: ['setup-scope'], queryFn: async () => (await httpClient.get('/settings/company/search-scope')).data });
  const existingProducts = useQuery({ queryKey: ['products', 'setup'], queryFn: () => productsApi.list({ limit: 5 }) });

  const [step, setStep] = useState(0);
  const [business, setBusiness] = useState({ industryKey: '', description: '', website: '' });
  const [place, setPlace] = useState({ city: '', latitude: null, longitude: null, radius: 5 });
  const [products, setProducts] = useState([{ name: '', price: '' }]);
  const [filter, setFilter] = useState('');
  const [status, setStatus] = useState({ busy: false, error: null, locating: false });

  useEffect(() => {
    const c = company.data?.company;
    if (c) setBusiness((b) => ({ industryKey: b.industryKey || c.industryKey, description: b.description || c.description, website: b.website || c.website }));
  }, [company.data]);
  useEffect(() => {
    const s = scope.data;
    if (s) setPlace((p) => ({ ...p, city: p.city || s.city || '', latitude: p.latitude ?? s.latitude, longitude: p.longitude ?? s.longitude }));
  }, [scope.data]);

  const industryList = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    return (industries.data || []).filter((i) => !needle || i.label.en.toLowerCase().includes(needle) || i.label.ar.includes(needle));
  }, [industries.data, filter]);

  if (company.isPending || industries.isPending) return <div className="setup-page" dir={dir}><Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel></div>;
  if (company.isError || industries.isError) return <div className="setup-page" dir={dir}><Panel><StateBlock kind="error" title={t('setup.loadError')} onRetry={() => { company.refetch(); industries.refetch(); }} retryLabel={t('demandApex.actions.retry')} /></Panel></div>;

  const info = company.data.company;
  const currency = info.currency;
  const hasProducts = (existingProducts.data?.total || 0) > 0;
  const filledProducts = products.filter((p) => p.name.trim() && p.price !== '' && Number(p.price) >= 0);

  const run = async (action, next) => {
    setStatus({ busy: true, error: null, locating: false });
    try {
      await action();
      setStatus({ busy: false, error: null, locating: false });
      next();
    } catch (error) {
      const detail = error?.response?.data?.detail;
      setStatus({ busy: false, error: typeof detail === 'string' ? detail : t('setup.saveError'), locating: false });
    }
  };

  const saveBusiness = () => run(() => companyApi.updateCompany({
    name: info.name, industryKey: business.industryKey, description: business.description.trim(), website: business.website.trim(),
  }), () => setStep(1));

  const saveLocation = () => run(() => httpClient.patch('/settings/company/search-scope', {
    city: place.city.trim() || null,
    ...(place.latitude != null ? { latitude: place.latitude, longitude: place.longitude } : {}),
    search_scope_level: 'CUSTOM', custom_radius_km: place.radius,
  }), () => setStep(2));

  const saveProducts = () => run(async () => {
    for (const p of filledProducts) {
      const name = p.name.trim();
      await productsApi.create({ product_name: ARABIC.test(name) ? { en: name, ar: name } : { en: name }, current_price: Number(p.price), currency });
    }
    if (filledProducts.length) setProducts([{ name: '', price: '' }]);
  }, () => setStep(3));

  const finish = (scan) => run(async () => {
    await companyApi.completeOnboarding();
    if (scan) {
      try { await discoveryApi.start({ radiusKm: place.radius }); } catch { /* the scan can be started again from Competitors */ }
    }
    queryClient.clear();
  }, () => navigate(scan ? routePaths.market : routePaths.dashboard, { replace: true }));

  const locate = () => {
    if (!navigator.geolocation) { setStatus((s) => ({ ...s, error: t('setup.location.unsupported') })); return; }
    setStatus((s) => ({ ...s, locating: true, error: null }));
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setPlace((p) => ({ ...p, latitude: Number(position.coords.latitude.toFixed(6)), longitude: Number(position.coords.longitude.toFixed(6)) }));
        setStatus((s) => ({ ...s, locating: false }));
      },
      () => setStatus((s) => ({ ...s, locating: false, error: t('setup.location.denied') })),
      { enableHighAccuracy: false, timeout: 15000 },
    );
  };

  const industryLabel = (key) => {
    const found = (industries.data || []).find((i) => i.key === key);
    return found ? (isArabic ? found.label.ar : found.label.en) : t('setup.notSet');
  };

  return (
    <div className="setup-page" dir={dir}>
      <header className="setup-head">
        <p className="apex-eyebrow">{t('setup.eyebrow')}</p>
        <h1>{t('setup.title', { name: info.name })}</h1>
        <p className="apex-muted">{t('setup.subtitle')}</p>
        <ol className="setup-steps" aria-label={t('setup.progress')}>
          {STEPS.map((key, index) => (
            <li key={key} className={index === step ? 'is-current' : index < step ? 'is-done' : ''} aria-current={index === step ? 'step' : undefined}>
              <span>{index < step ? <Check size={13} aria-hidden="true" /> : index + 1}</span>{t(`setup.steps.${key}`)}
            </li>
          ))}
        </ol>
      </header>

      <Panel className="setup-panel">
        {step === 0 && (
          <div className="setup-form">
            <h2>{t('setup.business.title')}</h2>
            <p className="apex-muted">{t('setup.business.subtitle')}</p>
            <input className="apex-input" type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('setup.business.search')} aria-label={t('setup.business.search')} />
            <div className="setup-industries" role="radiogroup" aria-label={t('setup.business.industry')}>
              {industryList.map((i) => (
                <button key={i.key} type="button" role="radio" aria-checked={business.industryKey === i.key} onClick={() => setBusiness({ ...business, industryKey: i.key })}>
                  <Store size={15} aria-hidden="true" />{isArabic ? i.label.ar : i.label.en}
                </button>
              ))}
            </div>
            <label className="setup-field"><span>{t('setup.business.description')}</span>
              <textarea className="apex-input" rows={2} maxLength={1000} value={business.description} placeholder={t('settings.company.descriptionPlaceholder')} onChange={(e) => setBusiness({ ...business, description: e.target.value })} /></label>
            <label className="setup-field"><span>{t('setup.business.website')}</span>
              <input className="apex-input" dir="ltr" value={business.website} placeholder="example.com" onChange={(e) => setBusiness({ ...business, website: e.target.value })} /></label>
          </div>
        )}

        {step === 1 && (
          <div className="setup-form">
            <h2>{t('setup.location.title')}</h2>
            <p className="apex-muted">{t('setup.location.subtitle', { country: countryName(info.country, locale) })}</p>
            <label className="setup-field"><span>{t('setup.location.city')}</span>
              <input className="apex-input" value={place.city} maxLength={150} placeholder={t('setup.location.cityPlaceholder')} onChange={(e) => setPlace({ ...place, city: e.target.value })} /></label>
            <div className="setup-locate">
              <ApexButton variant="secondary" icon={Crosshair} loading={status.locating} onClick={locate}>{t('setup.location.useMine')}</ApexButton>
              {place.latitude != null && <span className="apex-muted"><MapPin size={13} aria-hidden="true" /> {t('setup.location.pinned', { lat: place.latitude.toFixed(4), lon: place.longitude.toFixed(4) })}</span>}
            </div>
            <fieldset className="setup-field">
              <legend>{t('setup.location.radius')}</legend>
              <div className="apex-segmented" role="group">
                {RADII.map((r) => <button key={r} type="button" aria-pressed={place.radius === r} onClick={() => setPlace({ ...place, radius: r })}>{t('discovery.list.km', { km: r })}</button>)}
              </div>
              <p className="apex-muted setup-note">{t('setup.location.radiusHint')}</p>
            </fieldset>
          </div>
        )}

        {step === 2 && (
          <div className="setup-form">
            <h2>{t('setup.products.title')}</h2>
            <p className="apex-muted">{t(hasProducts ? 'setup.products.subtitleHas' : 'setup.products.subtitle', { count: existingProducts.data?.total || 0 })}</p>
            {products.map((p, index) => (
              <div className="setup-product" key={index}>
                <input className="apex-input" value={p.name} maxLength={200} placeholder={t('setup.products.name')} aria-label={t('setup.products.name')} onChange={(e) => setProducts(products.map((x, i) => (i === index ? { ...x, name: e.target.value } : x)))} />
                <input className="apex-input" type="number" min="0" step="any" inputMode="decimal" value={p.price} placeholder={t('setup.products.price', { currency })} aria-label={t('setup.products.price', { currency })} onChange={(e) => setProducts(products.map((x, i) => (i === index ? { ...x, price: e.target.value } : x)))} />
                {products.length > 1 && <ApexButton size="sm" variant="ghost" icon={Trash2} aria-label={t('setup.products.remove')} onClick={() => setProducts(products.filter((_, i) => i !== index))} />}
              </div>
            ))}
            {products.length < 10 && <ApexButton size="sm" variant="ghost" icon={Plus} onClick={() => setProducts([...products, { name: '', price: '' }])}>{t('setup.products.add')}</ApexButton>}
            <p className="apex-muted setup-note"><Package size={13} aria-hidden="true" /> {t('setup.products.importHint')}</p>
          </div>
        )}

        {step === 3 && (
          <div className="setup-form">
            <h2>{t('setup.finish.title')}</h2>
            <dl className="competitor-facts">
              <div><dt>{t('setup.business.industry')}</dt><dd>{industryLabel(business.industryKey)}</dd></div>
              <div><dt>{t('setup.location.city')}</dt><dd>{place.city || (place.latitude != null ? t('discovery.pinnedLocation') : t('setup.notSet'))}</dd></div>
              <div><dt>{t('setup.location.radius')}</dt><dd>{t('discovery.list.km', { km: place.radius })}</dd></div>
            </dl>
            <p className="apex-muted">{t('setup.finish.subtitle')}</p>
          </div>
        )}

        {status.error && <p className="market-scan__note is-error" role="alert">{status.error}</p>}

        <div className="setup-actions">
          {step > 0 && <ApexButton variant="ghost" icon={ArrowLeft} disabled={status.busy} onClick={() => setStep(step - 1)}>{t('setup.back')}</ApexButton>}
          {step === 0 && <ApexButton icon={ArrowRight} loading={status.busy} disabled={!business.industryKey} onClick={saveBusiness}>{t('setup.next')}</ApexButton>}
          {step === 1 && <ApexButton icon={ArrowRight} loading={status.busy} disabled={!place.city.trim() && place.latitude == null} onClick={saveLocation}>{t('setup.next')}</ApexButton>}
          {step === 2 && <ApexButton icon={ArrowRight} loading={status.busy} onClick={saveProducts}>{filledProducts.length ? t('setup.products.save', { count: filledProducts.length }) : t('setup.skip')}</ApexButton>}
          {step === 3 && (
            <>
              <ApexButton variant="ghost" disabled={status.busy} onClick={() => finish(false)}>{t('setup.finish.later')}</ApexButton>
              <ApexButton icon={Radar} loading={status.busy} onClick={() => finish(true)}>{t('setup.finish.scan')}</ApexButton>
            </>
          )}
        </div>
      </Panel>
    </div>
  );
}

export default SetupPage;

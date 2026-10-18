import { useState } from 'react';
import { ArrowLeft, Building2, Globe2, Layers, Package, Search } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Panel } from '../../../shared/components/apex/Apex.jsx';
import { useDebounce } from '../../../shared/hooks/useDebounce.js';
import { productsApi } from '../../products/api/productsApi.js';
import { useAddCompetitor } from '../hooks/useAddCompetitor.js';

// Adding a competitor: who they are, and how they compete - with the whole
// business (another grocery store) or on specific products (a coffee
// roaster against your coffee). Only fields the API stores are asked for.
const PICKER_LIMIT = 50;

export function AddCompetitorPage() {
  const { t, dir } = useI18n();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const fromProduct = params.get('product');
  const addCompetitor = useAddCompetitor();
  const [name, setName] = useState('');
  const [website, setWebsite] = useState('');
  const [level, setLevel] = useState(fromProduct ? 'PRODUCT' : 'MARKET');
  const [selected, setSelected] = useState(() => new Set(fromProduct ? [fromProduct] : []));
  const [filter, setFilter] = useState('');
  const [errors, setErrors] = useState({});
  // Searched on the server, so any product can be picked however large the
  // catalogue is; ticked products stay selected while the search changes.
  const term = useDebounce(filter.trim(), 300);
  const products = useQuery({
    queryKey: ['products', 'picker', term],
    queryFn: () => productsApi.list({ limit: PICKER_LIMIT, search: term || undefined }),
    enabled: level === 'PRODUCT',
    placeholderData: keepPreviousData,
  });
  const visible = products.data?.products ?? [];
  const moreMatches = Math.max(0, (products.data?.total ?? 0) - visible.length);

  const toggle = (id) => setSelected((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  const back = () => navigate(fromProduct ? routePaths.productDetail.replace(':productId', fromProduct) : routePaths.market);

  const submit = async (event) => {
    event.preventDefault();
    const next = {};
    const typed = website.trim();
    const url = typed && !typed.includes('://') ? `https://${typed}` : typed;
    if (!name.trim()) next.name = t('market.modal.required');
    if (!url) next.website = t('market.modal.required');
    else {
      try { const parsed = new URL(url); if (!['http:', 'https:'].includes(parsed.protocol) || !parsed.hostname.includes('.')) throw new Error(); } catch { next.website = t('market.modal.invalidUrl'); }
    }
    if (level === 'PRODUCT' && selected.size === 0) next.products = t('competitorsApex.add.pickProducts');
    setErrors(next);
    if (Object.keys(next).length) return;
    try {
      await addCompetitor.mutateAsync({ name: name.trim(), website: url, competitionLevel: level, productIds: level === 'PRODUCT' ? [...selected] : [] });
      back();
    } catch {
      // addCompetitor.error is shown below.
    }
  };

  const planLimit = addCompetitor.error?.response?.status === 402;

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        <button type="button" className="apex-back" onClick={back}><ArrowLeft size={15} className="apex-flip-rtl" aria-hidden="true" />{t('market.detail.back')}</button>
        <PageHeader title={t('market.modal.title')} subtitle={t('competitorsApex.add.subtitle')} />
        <form className="apex-page" onSubmit={submit} dir={dir} noValidate>
          <Panel title={t('competitorsApex.add.who')}>
            <div className="apex-grid apex-grid--2">
              <label className="apex-field">
                <span>{t('market.modal.name')}</span>
                <span className="apex-input-icon"><Building2 size={16} aria-hidden="true" /><input className="apex-input" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={Boolean(errors.name)} maxLength={200} /></span>
                {errors.name && <small className="apex-field-error">{errors.name}</small>}
              </label>
              <label className="apex-field">
                <span>{t('market.modal.website')}</span>
                <span className="apex-input-icon"><Globe2 size={16} aria-hidden="true" /><input className="apex-input" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="rival.jo" aria-invalid={Boolean(errors.website)} dir="ltr" /></span>
                {errors.website && <small className="apex-field-error">{errors.website}</small>}
              </label>
            </div>
          </Panel>

          <Panel title={t('competitorsApex.add.how')} subtitle={t('competitorsApex.add.howHint')}>
            <div className="apex-choice-grid" role="radiogroup" aria-label={t('competitorsApex.add.how')}>
              {[['MARKET', Layers], ['PRODUCT', Package]].map(([value, Icon]) => (
                <button key={value} type="button" role="radio" aria-checked={level === value} className="apex-choice" onClick={() => setLevel(value)}>
                  <Icon size={20} aria-hidden="true" />
                  <strong>{t(`competitorsApex.level.${value}.title`)}</strong>
                  <span>{t(`competitorsApex.level.${value}.example`)}</span>
                </button>
              ))}
            </div>
            {level === 'PRODUCT' && (
              <div className="add-competitor-products">
                <div className="add-competitor-products__head">
                  <strong>{t('competitorsApex.add.whichProducts', { count: selected.size })}</strong>
                  <label className="apex-search"><Search size={15} aria-hidden="true" /><input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t('products.list.searchPlaceholder')} aria-label={t('products.list.searchPlaceholder')} /></label>
                </div>
                {errors.products && <small className="apex-field-error">{errors.products}</small>}
                <div className="add-competitor-products__list">
                  {visible.map((p) => (
                    <label key={p.product_id} className={`apex-check${selected.has(p.product_id) ? ' is-on' : ''}`}>
                      <input type="checkbox" checked={selected.has(p.product_id)} onChange={() => toggle(p.product_id)} />
                      <span>{p.product_name}</span>
                      {p.category && <small>{p.category}</small>}
                    </label>
                  ))}
                  {products.isSuccess && visible.length === 0 && <p className="apex-muted">{t('products.list.noResultsTitle')}</p>}
                  {moreMatches > 0 && <p className="apex-muted">{t('competitorsApex.add.moreProducts', { count: moreMatches })}</p>}
                </div>
              </div>
            )}
          </Panel>

          {addCompetitor.isError && (
            <div className="apex-notice apex-notice--danger" role="alert">
              {planLimit ? t('competitorsApex.add.planLimit', { limit: addCompetitor.error.response.data?.detail?.limit ?? '' }) : t('market.modal.submitError')}
              {planLimit && <ApexButton size="sm" variant="secondary" onClick={() => navigate(routePaths.billing)}>{t('competitorsApex.add.seePlans')}</ApexButton>}
            </div>
          )}
          <div className="apex-form-actions">
            <ApexButton variant="ghost" onClick={back}>{t('market.modal.cancel')}</ApexButton>
            <ApexButton type="submit" loading={addCompetitor.isPending}>{t('market.modal.submit')}</ApexButton>
          </div>
        </form>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

export default AddCompetitorPage;

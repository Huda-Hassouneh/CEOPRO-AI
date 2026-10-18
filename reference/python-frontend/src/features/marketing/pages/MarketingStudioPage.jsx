import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CalendarHeart, Check, FileText, ImageIcon, Link2, Megaphone, Package, Search, Sparkles, Tag, Target, Trash2,
} from 'lucide-react';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import { ApexButton, Pager, Panel, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useDebounce } from '../../../shared/hooks/useDebounce.js';
import { useSubmitLock } from '../../../shared/hooks/useSubmitLock.js';
import { productsApi } from '../../products/api/productsApi.js';
import httpClient from '../../../shared/lib/httpClient.js';
import { marketingApi } from '../api/marketingApi.js';
import { CampaignEditor, CampaignStatusPill } from '../components/CampaignEditor.jsx';
import { MarketingErrorMessage } from '../components/MarketingErrorMessage.jsx';
import { PhotoPicker } from '../components/PhotoPicker.jsx';
import { useMarketingOptions } from '../hooks/useMarketingOptions.js';
import { useCreateCampaign } from '../hooks/useCreateCampaign.js';
import { useCampaigns } from '../hooks/useCampaigns.js';
import { useDeleteCampaign } from '../hooks/useCampaignActions.js';
import '../styles/Marketing.css';

const STEPS = ['what', 'create', 'review'];
// What the owner wants the campaign to do -> the strategy and focus the writer understands.
const GOALS = {
  sell: { icon: Target, strategy: 'SALES_DRIVEN', focus: 'Sell more of this product' },
  offer: { icon: Tag, strategy: 'URGENCY', focus: 'Announce an offer or limited-time sale' },
  awareness: { icon: Megaphone, strategy: 'BRAND_AWARENESS', focus: 'Make more people know the brand' },
  seasonal: { icon: CalendarHeart, strategy: 'STORYTELLING', focus: 'Seasonal or occasion campaign', theme: 'SEASONAL' },
};
const THEMES = ['LUXURY_PREMIUM', 'MINIMAL_CLEAN', 'MODERN_TECH', 'SOCIAL_TRENDY', 'BOLD_PROMOTIONAL', 'LIFESTYLE', 'SEASONAL'];
const HISTORY_PAGE = 8;
// One image and the one caption that goes with it - nothing per platform.
const ONE_POST = ['INSTAGRAM'];

function newRequestKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID().replace(/-/g, '');
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

function CampaignHistory({ t, locale, dir, openId, onOpen, onDeleted }) {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [confirming, setConfirming] = useState(null);
  const term = useDebounce(search.trim(), 300);
  useEffect(() => setPage(0), [term]);
  const history = useCampaigns({ limit: HISTORY_PAGE, offset: page * HISTORY_PAGE, q: term || undefined });
  const remove = useDeleteCampaign();
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const number = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const data = history.data;

  return (
    <Panel
      eyebrow={t('marketingApex.history.eyebrow')}
      title={t('studio.historyTitle')}
      subtitle={data ? t('studio.historyCount', { count: data.total }) : null}
      actions={<label className="apex-search"><Search size={15} aria-hidden="true" /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('studio.searchHistory')} aria-label={t('studio.searchHistory')} /></label>}
    >
      {history.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : history.isError ? <StateBlock kind="error" compact title={t('dashboardActivity.loadError')} onRetry={() => history.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : !data.campaigns.length ? <StateBlock compact title={term ? t('studio.noMatch') : t('marketing.history.empty')} />
            : (
              <>
                <ul className="studio-history">
                  {data.campaigns.map((c) => (
                    <li key={c.campaign_id} className={openId === c.campaign_id ? 'is-open' : ''}>
                      <button type="button" className="studio-history__open" onClick={() => onOpen(c.campaign_id)} aria-current={openId === c.campaign_id ? 'true' : undefined}>
                        <span className="studio-history__icon" aria-hidden="true">{c.has_image ? <ImageIcon size={15} /> : <FileText size={15} />}</span>
                        <span><strong dir="auto">{c.campaign_brief}</strong><small className="apex-muted">{c.requested_at && date.format(new Date(c.requested_at))}{c.updated_at ? ` · ${t('studio.edited')}` : ''}</small></span>
                      </button>
                      <span className="studio-history__side">
                        <CampaignStatusPill status={c.status} t={t} />
                        {confirming === c.campaign_id ? (
                          <>
                            <ApexButton size="sm" variant="danger" loading={remove.isPending} onClick={() => remove.mutate(c.campaign_id, { onSuccess: () => { setConfirming(null); onDeleted(c.campaign_id); } })}>{t('studio.confirmDelete')}</ApexButton>
                            <ApexButton size="sm" variant="ghost" onClick={() => setConfirming(null)}>{t('studio.cancel')}</ApexButton>
                          </>
                        ) : (
                          <button type="button" className="studio-history__delete" onClick={() => setConfirming(c.campaign_id)} aria-label={t('studio.deleteNamed', { title: c.campaign_brief })}><Trash2 size={15} /></button>
                        )}
                      </span>
                    </li>
                  ))}
                </ul>
                {remove.isError && <MarketingErrorMessage error={remove.error} action="write" t={t} />}
                <Pager page={page} pageSize={HISTORY_PAGE} total={data.total} onChange={setPage} t={t} dir={dir} number={number} busy={history.isFetching} />
              </>
            )}
    </Panel>
  );
}

export default function MarketingStudioPage() {
  const { t, dir, locale } = useI18n();
  const [params, setParams] = useSearchParams();
  const options = useMarketingOptions();
  const createCampaign = useCreateCampaign();
  const runLocked = useSubmitLock();
  const queryClient = useQueryClient();

  const [source, setSource] = useState('product');
  const [productId, setProductId] = useState(params.get('product') || '');
  const [productSearch, setProductSearch] = useState('');
  const [url, setUrl] = useState('');
  const [description, setDescription] = useState('');
  const [goal, setGoal] = useState('sell');
  const [language, setLanguage] = useState(locale?.startsWith('ar') ? 'ar' : 'en');
  const [audience, setAudience] = useState('');
  const [theme, setTheme] = useState('');
  const [notes, setNotes] = useState('');
  const [photo, setPhoto] = useState(null);
  const [openId, setOpenId] = useState(params.get('campaign'));
  const [progress, setProgress] = useState(null); // 'copy' | 'image' while generating
  const [elapsed, setElapsed] = useState(0);
  const requestKey = useRef(null);
  const reviewRef = useRef(null);

  const term = useDebounce(productSearch.trim(), 250);
  const products = useQuery({ queryKey: ['products', 'marketing', term], queryFn: () => productsApi.list({ limit: 12, search: term || undefined }) });
  const chosen = useQuery({ queryKey: ['products', 'one', productId], queryFn: () => productsApi.getById(productId), enabled: Boolean(productId) });
  const suggestions = useQuery({
    queryKey: ['marketing-suggestions', source === 'product' ? productId : null],
    queryFn: async () => (await httpClient.get('/marketing/suggestions', { params: { product_id: source === 'product' && productId ? productId : undefined } })).data,
    enabled: goal === 'seasonal',
  });
  const openCampaign = useQuery({ queryKey: ['marketing-campaign', openId], queryFn: () => marketingApi.getCampaign(openId), enabled: Boolean(openId) });
  const [occasion, setOccasion] = useState(null);
  const capability = options.data?.capabilities?.image_generation
    ? { ...options.data.capabilities.image_generation, background_removal: options.data.capabilities.background_removal } : null;

  // Any change to what is being made is a new request; the same inputs pressed again reuse the key.
  useEffect(() => { requestKey.current = null; }, [source, productId, url, description, goal, language, audience, theme, notes, occasion]);
  useEffect(() => {
    if (!progress) return undefined;
    const started = Date.now();
    const timer = setInterval(() => {
      const seconds = Math.round((Date.now() - started) / 1000);
      setElapsed(seconds);
      if (seconds >= 6) setProgress('image');
    }, 1000);
    return () => clearInterval(timer);
  }, [progress === null]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (openCampaign.data) reviewRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, [openCampaign.data?.campaign_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const productName = (product) => {
    const name = product?.product_name;
    return name && typeof name === 'object' ? (name[locale] || name.en || Object.values(name)[0]) : name;
  };
  const ready = (source === 'product' && productId) || (source === 'link' && /^https?:\/\/.+\..+/i.test(url.trim())) || (source === 'describe' && description.trim().length >= 10);
  const step = progress ? 1 : openCampaign.data ? 2 : 0;

  const open = (id) => {
    setOpenId(id);
    setParams((current) => { const next = new URLSearchParams(current); if (id) next.set('campaign', id); else next.delete('campaign'); return next; }, { replace: true });
  };

  const generate = () => runLocked(async () => {
    if (!requestKey.current) requestKey.current = newRequestKey();
    setProgress('copy');
    setElapsed(0);
    try {
      const extra = [
        audience.trim() && `Audience: ${audience.trim()}.`,
        occasion && `Occasion: ${t(`marketingApex.occasions.${occasion.key}`)}.`,
        notes.trim(),
      ].filter(Boolean).join('\n');
      const campaign = await createCampaign.mutateAsync({
        productId: source === 'product' ? productId : undefined,
        url: source === 'link' ? url.trim() : undefined,
        text: source === 'describe' ? description.trim() : undefined,
        strategyType: GOALS[goal].strategy,
        focus: GOALS[goal].focus,
        creativeTheme: theme || occasion?.theme || GOALS[goal].theme || undefined,
        customCreativePrompt: extra || undefined,
        variantsPerPlatform: 1,
        platforms: ONE_POST,
        requestKey: requestKey.current,
        generateImage: Boolean(capability?.available),
        language,
      });
      if (photo) {
        try {
          await marketingApi.uploadCampaignImage({ campaignId: campaign.campaign_id, file: photo });
          await marketingApi.setReferenceSelection(campaign.campaign_id, 'ORIGINAL');
        } catch { /* the campaign is saved; the photo can be added again from the campaign */ }
      }
      requestKey.current = null;
      queryClient.setQueryData(['marketing-campaign', campaign.campaign_id], campaign);
      open(campaign.campaign_id);
      return campaign;
    } finally {
      setProgress(null);
    }
  }).catch(() => {});

  const rewrite = () => {
    const draft = openCampaign.data;
    if (!draft) return;
    runLocked(async () => {
      setProgress('copy');
      try {
        const campaign = await createCampaign.mutateAsync({
          productId: draft.product_id || undefined, url: draft.source_url || undefined,
          text: !draft.product_id && !draft.source_url ? draft.source_text : undefined,
          strategyType: draft.strategy_type, focus: draft.focus || undefined, creativeTheme: draft.creative_theme || undefined,
          customCreativePrompt: draft.custom_creative_prompt || undefined, variantsPerPlatform: 1, platforms: ONE_POST,
          requestKey: newRequestKey(), generateImage: Boolean(capability?.available), language,
        });
        queryClient.setQueryData(['marketing-campaign', campaign.campaign_id], campaign);
        open(campaign.campaign_id);
        return campaign;
      } finally {
        setProgress(null);
      }
    }).catch(() => {});
  };

  const productLabel = source === 'product' ? (productName(chosen.data?.product) || (products.data?.products ?? []).find((p) => p.product_id === productId)?.product_name) : null;

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        <PageHeader title={t('marketingApex.title')} subtitle={t('studio.subtitle')} />
        <div className="apex-page" dir={dir}>
          <ol className="mk-stepper studio-stepper" aria-label={t('marketingApex.progress')}>
            {STEPS.map((key, index) => (
              <li key={key} className={index === step ? 'is-current' : index < step ? 'is-done' : ''} aria-current={index === step ? 'step' : undefined}>
                <span className="studio-stepper__item"><span className="mk-stepper__dot">{index < step ? <Check size={13} /> : index + 1}</span><span className="studio-stepper__label">{t(`studio.steps.${key}`)}</span></span>
              </li>
            ))}
          </ol>

          <Panel eyebrow={t('studio.step1Eyebrow')} title={t('studio.step1Title')} subtitle={t('studio.step1Hint')}>
            <div className="mk-step">
              <div className="apex-segmented" role="tablist" aria-label={t('marketingApex.what.source')}>
                {[['product', Package], ['link', Link2], ['describe', FileText]].map(([key, Icon]) => (
                  <button key={key} type="button" role="tab" aria-selected={source === key} onClick={() => setSource(key)}><Icon size={14} aria-hidden="true" style={{ marginInlineEnd: 6, verticalAlign: '-2px' }} />{t(`marketingApex.what.${key}`)}</button>
                ))}
              </div>
              {source === 'product' && (
                <div className="mk-products">
                  <label className="apex-search apex-search--block"><Search size={15} aria-hidden="true" /><input type="search" value={productSearch} onChange={(e) => setProductSearch(e.target.value)} placeholder={t('products.list.searchPlaceholder')} aria-label={t('products.list.searchPlaceholder')} /></label>
                  <div className="mk-product-grid">
                    {productId && chosen.data?.product && !(products.data?.products ?? []).some((p) => p.product_id === productId) && (
                      <button type="button" className="mk-product is-on" aria-pressed="true"><Package size={16} /><span>{productName(chosen.data.product)}</span></button>
                    )}
                    {(products.data?.products ?? []).map((p) => (
                      <button key={p.product_id} type="button" className={`mk-product${productId === p.product_id ? ' is-on' : ''}`} aria-pressed={productId === p.product_id} onClick={() => setProductId(p.product_id)}>
                        <Package size={16} aria-hidden="true" /><span>{p.product_name}</span>{p.category && <small>{p.category}</small>}
                      </button>
                    ))}
                  </div>
                  {products.isSuccess && products.data.products.length === 0 && <p className="apex-muted">{t('studio.noProducts')}</p>}
                  <p className="apex-muted mk-note">{t('studio.productKnown')}</p>
                </div>
              )}
              {source === 'link' && (
                <label className="apex-field"><span>{t('marketingApex.what.linkLabel')}</span><input className="apex-input" dir="ltr" type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://yourshop.com/product" /><small className="apex-muted">{t('marketingApex.what.linkHint')}</small></label>
              )}
              {source === 'describe' && (
                <label className="apex-field"><span>{t('marketingApex.what.describeLabel')}</span><textarea className="apex-input mk-textarea" rows={3} maxLength={1500} value={description} onChange={(e) => setDescription(e.target.value)} placeholder={t('marketingApex.what.describePlaceholder')} /></label>
              )}

              <fieldset className="studio-goals">
                <legend>{t('studio.goalLabel')}</legend>
                <div className="apex-choice-grid">
                  {Object.entries(GOALS).map(([key, { icon: Icon }]) => (
                    <button key={key} type="button" role="radio" aria-checked={goal === key} className="apex-choice" onClick={() => setGoal(key)}>
                      <Icon size={20} aria-hidden="true" /><strong>{t(`studio.goals.${key}.title`)}</strong><span>{t(`studio.goals.${key}.description`)}</span>
                    </button>
                  ))}
                </div>
              </fieldset>

              {goal === 'seasonal' && suggestions.isSuccess && suggestions.data.occasions?.length > 0 && (
                <div className="mk-chips" role="group" aria-label={t('marketingApex.season.upcoming')}>
                  {suggestions.data.occasions.slice(0, 6).map((o) => (
                    <button key={`${o.key}-${o.starts}`} type="button" className="apex-chip" aria-pressed={occasion?.key === o.key} onClick={() => setOccasion(occasion?.key === o.key ? null : o)}>
                      {t(`marketingApex.occasions.${o.key}`)}
                    </button>
                  ))}
                </div>
              )}

              <div className="studio-language" role="group" aria-label={t('studio.language')}>
                <span>{t('studio.language')}</span>
                <div className="apex-segmented">
                  {['en', 'ar'].map((code) => <button key={code} type="button" aria-pressed={language === code} onClick={() => setLanguage(code)}>{t(`studio.languages.${code}`)}</button>)}
                </div>
              </div>

              <details className="studio-more">
                <summary>{t('studio.options')}</summary>
                <div className="mk-step">
                  <label className="apex-field"><span>{t('studio.audienceLabel')}</span><input className="apex-input" dir="auto" maxLength={200} value={audience} onChange={(e) => setAudience(e.target.value)} placeholder={t('studio.audiencePlaceholder')} /></label>
                  <label className="apex-field"><span>{t('studio.lookLabel')}</span>
                    <select className="apex-input" value={theme} onChange={(e) => setTheme(e.target.value)}>
                      <option value="">{t('marketingApex.style.auto')}</option>
                      {THEMES.map((key) => <option key={key} value={key}>{t(`marketingApex.style.names.${key}`)}</option>)}
                    </select>
                  </label>
                  <label className="apex-field"><span>{t('studio.notesLabel')}</span><textarea className="apex-input mk-textarea" rows={2} maxLength={1200} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t('marketingApex.direction.placeholder')} /></label>
                  <div className="mk-photo">
                    <div><strong>{t('marketingApex.what.photoTitle')}</strong><p className="apex-muted">{t('studio.photoHint')}</p></div>
                    <PhotoPicker file={photo} onChange={setPhoto} t={t} />
                  </div>
                </div>
              </details>
            </div>
          </Panel>

          <Panel eyebrow={t('studio.step2Eyebrow')} title={t('studio.step2Title')} subtitle={capability?.available ? t('studio.step2Hint') : t('studio.step2HintNoImage')}>
            {progress ? (
              <div className="studio-progress" role="status" aria-live="polite">
                <span className="apex-spinner" aria-hidden="true" />
                <div>
                  <strong>{progress === 'copy' ? t('studio.writing') : t('studio.creatingImage')}</strong>
                  <p className="apex-muted">{t('studio.elapsed', { seconds: elapsed })} · {t('studio.keepOpen')}</p>
                </div>
              </div>
            ) : (
              <div className="studio-generate">
                <p className="apex-muted">{ready ? t('studio.summary', { what: source === 'product' ? (productLabel || '') : source === 'link' ? url.trim() : t('studio.yourDescription'), goal: t(`studio.goals.${goal}.title`), language: t(`studio.languages.${language}`) }) : t('studio.chooseFirst')}</p>
                <ApexButton size="lg" icon={Sparkles} disabled={!ready} loading={createCampaign.isPending} onClick={generate}>{t('studio.generate')}</ApexButton>
              </div>
            )}
            {capability?.external && !progress && <p className="apex-muted studio-note">{t('studio.imagePrivacy')}</p>}
            {createCampaign.isError && !progress && <MarketingErrorMessage error={createCampaign.error} action="write" source={source} t={t} className="apex-notice apex-notice--danger" />}
          </Panel>

          <div ref={reviewRef}>
            {openId && openCampaign.isPending && <Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel>}
            {openId && openCampaign.isError && <Panel><StateBlock kind="error" title={t('studio.openFailed')} onRetry={() => openCampaign.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel>}
            {openCampaign.data && (openCampaign.data.status === 'FAILED'
              ? <Panel><StateBlock kind="error" compact title={t('marketingApex.result.failedCampaign')} description={t('marketingApex.errors.failed')} /></Panel>
              : <CampaignEditor campaign={openCampaign.data} capability={capability} t={t} locale={locale}
                  onDeleted={() => open(null)} onRewrite={rewrite} rewriting={Boolean(progress)} />)}
          </div>

          <CampaignHistory t={t} locale={locale} dir={dir} openId={openId} onOpen={open} onDeleted={(id) => { if (id === openId) open(null); }} />
        </div>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

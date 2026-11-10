import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, FileText, ImageIcon, Link2, Package, Search, Sparkles, Trash2, X } from 'lucide-react';
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
import { createPostWithPhoto } from '../api/createWithPhoto.js';
import { CampaignEditor, CampaignStatusPill, PLATFORM_FORMAT } from '../components/CampaignEditor.jsx';
import { DEFAULT_IMAGE_FORMATS } from '../components/ImageStudio.jsx';
import { MarketingErrorMessage } from '../components/MarketingErrorMessage.jsx';
import { PhotoPicker } from '../components/PhotoPicker.jsx';
import { useMarketingOptions } from '../hooks/useMarketingOptions.js';
import { useCreateCampaign } from '../hooks/useCreateCampaign.js';
import { useCampaigns } from '../hooks/useCampaigns.js';
import { useDeleteCampaign } from '../hooks/useCampaignActions.js';
import { useImageCapacity } from '../hooks/useImageJobs.js';
import '../styles/Marketing.css';

// What the owner wants the post to do -> the strategy and focus the writer understands.
const GOALS = {
  sell: { strategy: 'SALES_DRIVEN', focus: 'Sell more of this product' },
  offer: { strategy: 'URGENCY', focus: 'Announce an offer or limited-time sale' },
  awareness: { strategy: 'BRAND_AWARENESS', focus: 'Make more people know the brand' },
  seasonal: { strategy: 'STORYTELLING', focus: 'Seasonal or occasion campaign', theme: 'SEASONAL' },
};
// Where it will be posted -> which copy is written and the picture's shape.
const PLACES = {
  instagram: { platform: 'INSTAGRAM', format: 'SQUARE' },
  story: { platform: 'INSTAGRAM', format: 'STORY' },
  facebook: { platform: 'FACEBOOK', format: PLATFORM_FORMAT.FACEBOOK },
  tiktok: { platform: 'TIKTOK', format: PLATFORM_FORMAT.TIKTOK },
  google: { platform: 'GOOGLE_ADS', format: PLATFORM_FORMAT.GOOGLE_ADS },
};
// Sent to the writer in English whatever the screen language.
const AUDIENCES = {
  anyone: null, families: 'Families', young: 'Young adults (18-30)', gifts: 'People buying a gift',
  professionals: 'Busy working professionals', students: 'Students', custom: null,
};
const TONES = { auto: null, friendly: 'Friendly', professional: 'Professional', exciting: 'Exciting', elegant: 'Elegant', warm: 'Warm' };
const THEMES = ['LUXURY_PREMIUM', 'MINIMAL_CLEAN', 'MODERN_TECH', 'SOCIAL_TRENDY', 'BOLD_PROMOTIONAL', 'LIFESTYLE', 'SEASONAL'];
const HISTORY_PAGE = 8;
const URL_PATTERN = /^https?:\/\/\S+\.\S+/i;

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
      className="studio-all"
      title={t('studio.result.myPosts')}
      subtitle={data?.total ? t('studio.result.historyHint') : null}
      actions={<label className="apex-search"><Search size={15} aria-hidden="true" /><input type="search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t('studio.searchHistory')} aria-label={t('studio.searchHistory')} /></label>}
    >
      {history.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
        : history.isError ? <StateBlock kind="error" compact title={t('dashboardActivity.loadError')} onRetry={() => history.refetch()} retryLabel={t('demandApex.actions.retry')} />
          : !data.campaigns.length ? <StateBlock compact title={term ? t('studio.noMatch') : t('studio.one.noRecent')} />
            : (
              <>
                <ul className="studio-history">
                  {data.campaigns.map((c) => (
                    <li key={c.campaign_id} className={openId === c.campaign_id ? 'is-open' : ''}>
                      <button type="button" className="studio-history__open" onClick={() => onOpen(c.campaign_id)} aria-current={openId === c.campaign_id ? 'true' : undefined}>
                        <span className="studio-history__icon" aria-hidden="true">{c.has_image ? <ImageIcon size={16} /> : <FileText size={16} />}</span>
                        <span><strong dir="auto">{c.campaign_brief || t('studio.result.untitled')}</strong><small className="apex-muted">{c.requested_at && date.format(new Date(c.requested_at))}{c.updated_at ? ` · ${t('studio.edited')}` : ''}</small></span>
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

// The three newest posts, one tap to open; "See all posts" opens the full list.
function RecentPosts({ t, locale, openId, onOpen, showAll, onToggleAll }) {
  const recent = useCampaigns({ limit: 3, offset: 0 });
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }), [locale]);
  const list = recent.data?.campaigns ?? [];
  return (
    <section className="studio-recent" aria-labelledby="studio-recent-title">
      <header>
        <h2 id="studio-recent-title">{t('studio.one.recent')}</h2>
        {(recent.data?.total ?? 0) > 0 && (
          <button type="button" className="studio-link" aria-expanded={showAll} onClick={onToggleAll}>{showAll ? t('studio.one.hideAll') : t('studio.one.seeAll')}</button>
        )}
      </header>
      {recent.isSuccess && list.length === 0 && <p className="apex-muted">{t('studio.one.noRecent')}</p>}
      {list.length > 0 && (
        <ul className="studio-recent__list">
          {list.map((c) => (
            <li key={c.campaign_id}>
              <button type="button" className={`studio-recent__item${openId === c.campaign_id ? ' is-open' : ''}`} onClick={() => onOpen(c.campaign_id)} aria-current={openId === c.campaign_id ? 'true' : undefined}>
                <span className="studio-history__icon" aria-hidden="true">{c.has_image ? <ImageIcon size={16} /> : <FileText size={16} />}</span>
                <span><strong dir="auto">{c.campaign_brief || t('studio.result.untitled')}</strong><small className="apex-muted">{c.requested_at && date.format(new Date(c.requested_at))}</small></span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function MarketingStudioPage() {
  const { t, dir, locale } = useI18n();
  const [params, setParams] = useSearchParams();
  const options = useMarketingOptions();
  const createCampaign = useCreateCampaign();
  // With a live image worker the first image is queued, not made inside the create request.
  const imageQueue = useImageCapacity();
  const queueImages = Boolean(imageQueue.data?.available);
  const runLocked = useSubmitLock();
  const queryClient = useQueryClient();

  // What is promoted: one box. A product picked from the list, else a link, else a description.
  const [query, setQuery] = useState('');
  const [productId, setProductId] = useState(params.get('product') || '');
  // Everything else starts at a sensible default and lives under "Customize".
  const [place, setPlace] = useState('instagram');
  const [goal, setGoal] = useState('sell');
  const [occasionKey, setOccasionKey] = useState('');
  const [audienceKey, setAudienceKey] = useState('anyone');
  const [customAudience, setCustomAudience] = useState('');
  const [toneKey, setToneKey] = useState('auto');
  const [language, setLanguage] = useState(locale?.startsWith('ar') ? 'ar' : 'en');
  const [shape, setShape] = useState(''); // '' = the shape that suits `place`
  const [theme, setTheme] = useState('');
  const [notes, setNotes] = useState('');
  const [photo, setPhoto] = useState(null);
  const [showHint, setShowHint] = useState(false);
  const [openId, setOpenId] = useState(params.get('campaign'));
  const [showAll, setShowAll] = useState(false);
  const [progress, setProgress] = useState(null); // 'copy' | 'image' while creating
  const [elapsed, setElapsed] = useState(0);
  const requestKey = useRef(null);
  const resultRef = useRef(null);

  const term = useDebounce(query.trim(), 250);
  const searching = term && !URL_PATTERN.test(term) ? term : undefined;
  const products = useQuery({ queryKey: ['products', 'marketing', searching || ''], queryFn: () => productsApi.list({ limit: 6, search: searching }) });
  const chosen = useQuery({ queryKey: ['products', 'one', productId], queryFn: () => productsApi.getById(productId), enabled: Boolean(productId) });
  const suggestions = useQuery({
    queryKey: ['marketing-suggestions', productId || null],
    queryFn: async () => (await httpClient.get('/marketing/suggestions', { params: { product_id: productId || undefined } })).data,
    enabled: goal === 'seasonal',
  });
  const openCampaign = useQuery({ queryKey: ['marketing-campaign', openId], queryFn: () => marketingApi.getCampaign(openId), enabled: Boolean(openId) });
  const capability = options.data?.capabilities?.image_generation
    ? { ...options.data.capabilities.image_generation, background_removal: options.data.capabilities.background_removal } : null;
  const formats = options.data?.image_formats ?? DEFAULT_IMAGE_FORMATS;

  const productName = (product) => {
    const name = product?.product_name;
    return name && typeof name === 'object' ? (name[locale] || name.en || Object.values(name)[0]) : name;
  };
  const productList = products.data?.products ?? [];
  const chosenName = productName(chosen.data?.product) || productName(productList.find((p) => p.product_id === productId));
  const text = query.trim();
  const source = productId ? 'product' : URL_PATTERN.test(text) ? 'link' : text.length >= 10 ? 'describe' : null;
  const occasion = (suggestions.data?.occasions ?? []).find((o) => o.key === occasionKey) || null;
  const audienceText = audienceKey === 'custom' ? customAudience.trim() : AUDIENCES[audienceKey];
  const imageFormat = shape || PLACES[place].format;
  const placeName = t(`studio.wizard.places.${place}.title`);

  // Any change to what is being made is a new request; the same inputs pressed again reuse the key.
  useEffect(() => { requestKey.current = null; }, [query, productId, place, goal, occasionKey, audienceText, toneKey, language, shape, theme, notes]);
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

  const scrollToResult = () => globalThis.setTimeout(() => {
    if (globalThis.matchMedia?.('(max-width: 1023px)').matches) resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, 50);
  const open = (id) => {
    setOpenId(id);
    setParams((current) => { const next = new URLSearchParams(current); if (id) next.set('campaign', id); else next.delete('campaign'); return next; }, { replace: true });
    if (id) scrollToResult();
  };
  const pickProduct = (p) => { setProductId(p.product_id); setQuery(''); setShowHint(false); };
  const clearWhat = () => { setProductId(''); setQuery(''); };

  const generate = () => {
    if (!source) { setShowHint(true); return undefined; }
    return runLocked(async () => {
      if (!requestKey.current) requestKey.current = newRequestKey();
      setProgress('copy');
      setElapsed(0);
      scrollToResult();
      try {
        const extra = [
          audienceText && `Audience: ${audienceText}.`,
          occasion && `Occasion: ${t(`marketingApex.occasions.${occasion.key}`)}.`,
          notes.trim(),
        ].filter(Boolean).join('\n');
        const campaign = await createPostWithPhoto({
          ...marketingApi, createCampaign: createCampaign.mutateAsync,
        }, {
          request: {
            productId: source === 'product' ? productId : undefined,
            url: source === 'link' ? text : undefined,
            text: source === 'describe' ? text : undefined,
            strategyType: GOALS[goal].strategy,
            focus: GOALS[goal].focus,
            tone: TONES[toneKey] || undefined,
            creativeTheme: theme || occasion?.theme || GOALS[goal].theme || undefined,
            customCreativePrompt: extra || undefined,
            variantsPerPlatform: 1,
            platforms: [PLACES[place].platform],
            requestKey: requestKey.current,
            language,
          },
          photo, queueImages, imageFormat,
        });
        requestKey.current = null;
        queryClient.setQueryData(['marketing-campaign', campaign.campaign_id], campaign);
        if (photo) {  // the stored campaign now has the photo and its picture
          queryClient.invalidateQueries({ queryKey: ['marketing-campaign', campaign.campaign_id] });
          queryClient.invalidateQueries({ queryKey: ['marketing-assets', campaign.campaign_id] });
        }
        open(campaign.campaign_id);
        return campaign;
      } finally {
        setProgress(null);
      }
    }).catch(() => {});
  };

  const rewrite = () => {
    const draft = openCampaign.data;
    if (!draft) return;
    const platforms = Object.keys(draft.content || {});
    const format = PLATFORM_FORMAT[platforms[0]] || 'SQUARE';
    runLocked(async () => {
      setProgress('copy');
      try {
        const campaign = await createCampaign.mutateAsync({
          productId: draft.product_id || undefined, url: draft.source_url || undefined,
          text: !draft.product_id && !draft.source_url ? draft.source_text : undefined,
          strategyType: draft.strategy_type, focus: draft.focus || undefined, creativeTheme: draft.creative_theme || undefined,
          customCreativePrompt: draft.custom_creative_prompt || undefined, variantsPerPlatform: 1,
          platforms: platforms.length ? platforms : ['INSTAGRAM'],
          requestKey: newRequestKey(), generateImage: !queueImages, imageFormat: format, language,
        });
        if (queueImages) {
          await marketingApi.queueImageBatch(campaign.campaign_id, { formats: [format], variations: 1, attachFirst: true }).catch(() => {});
        }
        queryClient.setQueryData(['marketing-campaign', campaign.campaign_id], campaign);
        open(campaign.campaign_id);
        return campaign;
      } finally {
        setProgress(null);
      }
    }).catch(() => {});
  };

  const usingLine = source === 'product' ? t('studio.one.usingProduct', { name: chosenName || '…' })
    : source === 'link' ? t('studio.one.usingLink', { url: text.replace(/^https?:\/\//i, '').slice(0, 48) })
      : source === 'describe' ? t('studio.one.usingDescribe') : null;
  const SourceIcon = source === 'link' ? Link2 : source === 'describe' ? FileText : Package;
  const defaultsLine = [placeName, t(`studio.goals.${goal}.title`), t(`studio.languages.${language}`), t(`studio.formatsPlain.${imageFormat}.title`)].join(' · ');

  const Working = (
    <div className="studio-working" role="status" aria-live="polite">
      <span className="apex-spinner" aria-hidden="true" />
      <div>
        <strong>{t('studio.one.working')}</strong>
        <ul className="studio-working__steps">
          <li className={progress === 'image' ? 'is-done' : 'is-current'}>{progress === 'image' ? <Check size={14} aria-hidden="true" /> : <span className="studio-working__dot" aria-hidden="true" />}{t('studio.wizard.workingText')}</li>
          <li className={progress === 'image' ? 'is-current' : ''}><span className="studio-working__dot" aria-hidden="true" />{t('studio.wizard.workingImage')}</li>
        </ul>
        <p className="apex-muted">{t('studio.wizard.workingKeep')} · {t('studio.elapsed', { seconds: elapsed })}</p>
      </div>
    </div>
  );

  return (
    <DashboardLayout>
      <BusinessPageContainer>
        <PageHeader title={t('marketingApex.title')} subtitle={t('studio.subtitle')} />
        <div className="apex-page studio-page studio-one" dir={dir}>
          <div className="studio-workspace">
            <section className="apex-panel studio-create" aria-labelledby="studio-create-title">
              <div className="apex-panel__body">
                <header className="studio-create__head">
                  <h2 id="studio-create-title">{t('studio.one.title')}</h2>
                  <p>{t('studio.one.hint')}</p>
                </header>

                <div className="studio-what">
                  <label htmlFor="studio-what-input" className="studio-what__label">{t('studio.one.whatLabel')}</label>
                  {productId ? (
                    <div className="studio-what__chosen">
                      <Package size={18} aria-hidden="true" />
                      <strong dir="auto">{chosenName || t('common.loading')}</strong>
                      <button type="button" className="studio-close" onClick={clearWhat} aria-label={t('studio.one.clear')}><X size={16} /></button>
                    </div>
                  ) : (
                    <div className="studio-what__box">
                      <Search size={17} aria-hidden="true" />
                      <textarea id="studio-what-input" className="mk-textarea studio-what__input" rows={1} maxLength={1500} dir="auto"
                        value={query} onChange={(e) => { setQuery(e.target.value); setShowHint(false); }}
                        onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && source) { e.preventDefault(); generate(); } }}
                        placeholder={t('studio.one.whatPlaceholder')} aria-describedby="studio-what-help" />
                      {query && <button type="button" className="studio-close" onClick={clearWhat} aria-label={t('studio.one.clear')}><X size={16} /></button>}
                    </div>
                  )}
                  {!productId && productList.length > 0 && !URL_PATTERN.test(text) && (
                    <div className="mk-chips studio-what__products" role="group" aria-label={t('marketingApex.what.product')}>
                      {productList.map((p) => (
                        <button key={p.product_id} type="button" className="apex-chip" onClick={() => pickProduct(p)}>
                          <Package size={13} aria-hidden="true" />{productName(p)}
                        </button>
                      ))}
                    </div>
                  )}
                  <p id="studio-what-help" className={`studio-what__help${usingLine ? ' is-set' : ''}`}>
                    {usingLine ? <><SourceIcon size={14} aria-hidden="true" />{usingLine}</> : t('studio.one.whatHint')}
                  </p>
                  {showHint && !source && <p className="apex-notice apex-notice--warning studio-hint" role="alert">{t('studio.one.usingNone')}</p>}
                </div>

                {progress ? Working : (
                  <div className="studio-generate">
                    <ApexButton size="lg" icon={Sparkles} loading={createCampaign.isPending} onClick={generate}>{t('studio.one.create')}</ApexButton>
                    <p className="studio-defaults">{defaultsLine}</p>
                  </div>
                )}
                {createCampaign.isError && !progress && <MarketingErrorMessage error={createCampaign.error} action="write" source={source} t={t} className="apex-notice apex-notice--danger" />}

                <details className="studio-fold studio-customize">
                  <summary>{t('studio.one.customize')}</summary>
                  <div className="studio-customize__grid">
                    <div className="apex-field"><label htmlFor="studio-opt-1">{t('studio.one.where')}</label>
                      <select id="studio-opt-1" className="apex-input" value={place} onChange={(e) => setPlace(e.target.value)}>
                        {Object.keys(PLACES).map((key) => <option key={key} value={key}>{t(`studio.wizard.places.${key}.title`)}</option>)}
                      </select>
                    </div>
                    <div className="apex-field"><label htmlFor="studio-opt-2">{t('studio.one.goal')}</label>
                      <select id="studio-opt-2" className="apex-input" value={goal} onChange={(e) => setGoal(e.target.value)}>
                        {Object.keys(GOALS).map((key) => <option key={key} value={key}>{t(`studio.goals.${key}.title`)}</option>)}
                      </select>
                    </div>
                    {goal === 'seasonal' && (
                      <div className="apex-field studio-customize__wide"><label htmlFor="studio-opt-3">{t('studio.one.occasion')}</label>
                        <select id="studio-opt-3" className="apex-input" value={occasionKey} onChange={(e) => setOccasionKey(e.target.value)}>
                          <option value="">{t('studio.one.occasionNone')}</option>
                          {(suggestions.data?.occasions ?? []).slice(0, 8).map((o) => <option key={`${o.key}-${o.starts}`} value={o.key}>{t(`marketingApex.occasions.${o.key}`)}</option>)}
                        </select>
                      </div>
                    )}
                    <div className="apex-field"><label htmlFor="studio-opt-4">{t('studio.one.who')}</label>
                      <select id="studio-opt-4" className="apex-input" value={audienceKey} onChange={(e) => setAudienceKey(e.target.value)}>
                        {Object.keys(AUDIENCES).map((key) => <option key={key} value={key}>{t(`studio.wizard.audiences.${key}`)}</option>)}
                      </select>
                    </div>
                    <div className="apex-field"><label htmlFor="studio-opt-5">{t('studio.one.tone')}</label>
                      <select id="studio-opt-5" className="apex-input" value={toneKey} onChange={(e) => setToneKey(e.target.value)}>
                        {Object.keys(TONES).map((key) => <option key={key} value={key}>{t(`studio.one.tones.${key}`)}</option>)}
                      </select>
                    </div>
                    {audienceKey === 'custom' && (
                      <div className="apex-field studio-customize__wide"><label htmlFor="studio-opt-6">{t('studio.wizard.customAudience')}</label>
                        <input id="studio-opt-6" className="apex-input" dir="auto" maxLength={200} value={customAudience} onChange={(e) => setCustomAudience(e.target.value)} placeholder={t('studio.audiencePlaceholder')} />
                      </div>
                    )}
                    <div className="apex-field"><label htmlFor="studio-opt-7">{t('studio.one.language')}</label>
                      <select id="studio-opt-7" className="apex-input" value={language} onChange={(e) => setLanguage(e.target.value)}>
                        {['en', 'ar'].map((code) => <option key={code} value={code}>{t(`studio.languages.${code}`)}</option>)}
                      </select>
                    </div>
                    <div className="apex-field"><label htmlFor="studio-opt-8">{t('studio.one.shape')}</label>
                      <select id="studio-opt-8" className="apex-input" value={shape} onChange={(e) => setShape(e.target.value)}>
                        <option value="">{t('studio.one.shapeAuto', { place: placeName })}</option>
                        {formats.map((f) => <option key={f.key} value={f.key}>{t(`studio.formatsPlain.${f.key}.title`)} - {t(`studio.formatsPlain.${f.key}.hint`)}</option>)}
                      </select>
                    </div>
                    <div className="apex-field studio-customize__wide"><label htmlFor="studio-opt-9">{t('studio.one.style')}</label>
                      <select id="studio-opt-9" className="apex-input" value={theme} onChange={(e) => setTheme(e.target.value)}>
                        <option value="">{t('marketingApex.style.auto')}</option>
                        {THEMES.map((key) => <option key={key} value={key}>{t(`marketingApex.style.names.${key}`)}</option>)}
                      </select>
                    </div>
                    <div className="apex-field studio-customize__wide"><label htmlFor="studio-opt-10">{t('studio.wizard.notesLabel')}</label>
                      <textarea id="studio-opt-10" className="apex-input" dir="auto" rows={2} maxLength={1200} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder={t('studio.wizard.notesPlaceholder')} />
                    </div>
                    <div className="mk-photo studio-customize__wide">
                      <div><strong>{t('marketingApex.what.photoTitle')}</strong><p className="apex-muted">{t('studio.wizard.photoHint')}</p></div>
                      <PhotoPicker file={photo} onChange={setPhoto} t={t} />
                    </div>
                  </div>
                </details>
                {capability?.external && <p className="apex-muted studio-note">{t('studio.wizard.privacy')}</p>}
              </div>
            </section>

            <div className="studio-output" ref={resultRef}>
              {progress && openId && <div className="apex-panel studio-result__working">{Working}</div>}
              {!openId ? (
                <section className="apex-panel studio-empty" aria-labelledby="studio-empty-title">
                  <div className="apex-panel__body">
                    {progress ? Working : (
                      <>
                        <span className="studio-empty__art" aria-hidden="true"><ImageIcon size={34} /></span>
                        <h2 id="studio-empty-title">{t('studio.one.emptyTitle')}</h2>
                        <p>{t('studio.one.emptyHint')}</p>
                      </>
                    )}
                  </div>
                </section>
              ) : openCampaign.isPending ? <Panel><StateBlock kind="loading" title={t('common.loading')} /></Panel>
                : openCampaign.isError ? <Panel><StateBlock kind="error" title={t('studio.openFailed')} onRetry={() => openCampaign.refetch()} retryLabel={t('demandApex.actions.retry')} /></Panel>
                  : openCampaign.data.status === 'FAILED'
                    ? <Panel><StateBlock kind="error" compact title={t('marketingApex.result.failedCampaign')} description={t('marketingApex.errors.failed')} /></Panel>
                    : <CampaignEditor campaign={openCampaign.data} capability={capability} t={t} locale={locale}
                        imageFormats={options.data?.image_formats} assetChannels={options.data?.asset_channels}
                        onDeleted={() => open(null)} onRewrite={rewrite} rewriting={Boolean(progress)} />}
            </div>
          </div>

          <RecentPosts t={t} locale={locale} openId={openId} onOpen={open} showAll={showAll} onToggleAll={() => setShowAll((v) => !v)} />
          {showAll && <CampaignHistory t={t} locale={locale} dir={dir} openId={openId} onOpen={open} onDeleted={(id) => { if (id === openId) open(null); }} />}
        </div>
      </BusinessPageContainer>
    </DashboardLayout>
  );
}

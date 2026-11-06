import { useEffect, useMemo, useState } from 'react';
import { Check, CheckCircle2, Copy, ImagePlus, PenLine, RotateCcw, Save, Sparkles, Trash2, X } from 'lucide-react';
import { ApexButton, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { getAccountProfile } from '../../../shared/utils/accountProfile.js';
import { useDeleteCampaign, useUpdateCampaign } from '../hooks/useCampaignActions.js';
import { MarketingErrorMessage } from './MarketingErrorMessage.jsx';
import { DownloadPicture, NewPicturePanel, PictureFrame, PictureGallery, PictureNotes, useCampaignPictures } from './ImageStudio.jsx';
import { PostPreview } from './PostPreview.jsx';
import { ProductReferenceEditor } from './ProductReferenceEditor.jsx';

export const PLATFORM_LABELS = { INSTAGRAM: 'Instagram', FACEBOOK: 'Facebook', TIKTOK: 'TikTok', GOOGLE_ADS: 'Google Ads' };
const LIMITS = { GOOGLE_ADS: { headline: 30, body_copy: 90 } };
// The picture shape that suits each platform (a new picture starts there).
export const PLATFORM_FORMAT = { INSTAGRAM: 'SQUARE', FACEBOOK: 'SQUARE', TIKTOK: 'STORY', GOOGLE_ADS: 'WIDE' };

// The text a post needs, ready to paste: headline, caption, hashtags, call to action.
export function postText(platform, v) {
  if (platform === 'GOOGLE_ADS') return [v.headline, v.body_copy, v.cta].filter(Boolean).join('\n');
  return [v.headline, v.body_copy, (v.hashtags || []).join(' '), v.cta].filter(Boolean).join('\n\n');
}

function CopyText({ text, t }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      globalThis.setTimeout(() => setCopied(false), 1800);
    } catch { /* clipboard refused: the text stays selectable in the preview */ }
  };
  return (
    <button type="button" className="apex-btn apex-btn--primary studio-copy-btn" onClick={copy} aria-live="polite">
      {copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}{copied ? t('studio.result.copied') : t('studio.result.copyText')}
    </button>
  );
}

function hashtagsFromText(text) {
  return (text || '').split(/[\s,،]+/).map((s) => s.trim()).filter(Boolean).map((s) => (s.startsWith('#') ? s : `#${s}`));
}

// One saved post as the owner sees it: a preview that looks like the real
// post, the three things to do next (download, copy, post), and - one at a
// time, in the same place - changing the text or trying another picture.
// Everything else (where each picture is used, many pictures at once, the
// audience guess, the style notes, the product photo, deleting) is folded
// under "More options". Edits are kept until "Save changes".
export function CampaignEditor({ campaign, capability, imageFormats, assetChannels, t, locale, onDeleted, onRewrite, rewriting }) {
  const id = campaign.campaign_id;
  const platforms = Object.keys(campaign.content || {});
  const [platform, setPlatform] = useState(platforms[0]);
  const [title, setTitle] = useState(campaign.campaign_brief || '');
  const [audience, setAudience] = useState(campaign.audience_summary || '');
  const [edits, setEdits] = useState({});
  const [mode, setMode] = useState('next'); // 'next' | 'text' | 'picture'
  const [pendingFormat, setPendingFormat] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const update = useUpdateCampaign();
  const remove = useDeleteCampaign();
  const user = useAuthStore((state) => state.user);
  const profile = getAccountProfile(user, t);
  const businessName = profile.companyName !== t('common.notAvailable') ? profile.companyName : null;
  const when = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);
  const pictures = useCampaignPictures({ campaign, capability, formats: imageFormats, channels: assetChannels });

  useEffect(() => {
    setTitle(campaign.campaign_brief || '');
    setAudience(campaign.audience_summary || '');
    setEdits({});
    setConfirmDelete(false);
    setMode('next');
    setPlatform((current) => (campaign.content?.[current] ? current : Object.keys(campaign.content || {})[0]));
  }, [campaign]);

  const variantKey = (p, v) => `${p}:${v.variant_index}`;
  const current = (p, v) => ({ ...v, ...(edits[variantKey(p, v)] || {}) });
  const setField = (p, v, field, value) => setEdits((all) => ({ ...all, [variantKey(p, v)]: { ...(all[variantKey(p, v)] || {}), [field]: value } }));
  const dirty = Object.keys(edits).length > 0 || title.trim() !== (campaign.campaign_brief || '') || audience !== (campaign.audience_summary || '');
  const undo = () => { setEdits({}); setTitle(campaign.campaign_brief || ''); setAudience(campaign.audience_summary || ''); };

  const save = () => update.mutate({
    campaignId: id,
    title: title.trim() !== (campaign.campaign_brief || '') ? title.trim() : undefined,
    audienceSummary: audience !== (campaign.audience_summary || '') ? audience : undefined,
    variants: Object.entries(edits).map(([key, fields]) => {
      const [p, index] = key.split(':');
      return { platform: p, variant_index: Number(index), ...fields };
    }),
  }, { onSuccess: () => { setEdits({}); setMode('next'); } });

  const variants = campaign.content?.[platform] || [];
  const [variantIndex, setVariantIndex] = useState(0);
  useEffect(() => setVariantIndex(0), [platform, id]);
  const original = variants[Math.min(variantIndex, variants.length - 1)];
  const v = original ? current(platform, original) : {};
  const limits = LIMITS[platform] || {};
  const place = t(`studio.result.places.${platform}`, { defaultValue: PLATFORM_LABELS[platform] || platform });

  return (
    <section className="apex-panel studio-editor" aria-labelledby="studio-ready-title">
      <div className="apex-panel__body">
        <header className="studio-editor__head">
          <div className="studio-ready">
            <CheckCircle2 size={26} aria-hidden="true" />
            <div>
              <h2 id="studio-ready-title">{t('studio.result.readyTitle')}</h2>
              <p>{t('studio.result.readyHint')}</p>
            </div>
          </div>
          <label className="studio-title">
            <span className="sr-only">{t('studio.result.nameLabel')}</span>
            <PenLine size={14} aria-hidden="true" />
            <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} aria-label={t('studio.result.nameLabel')} dir="auto" placeholder={t('studio.result.untitled')} />
            <small className="apex-muted">{t('studio.result.savedAt', { date: when.format(new Date(campaign.updated_at || campaign.completed_at || campaign.requested_at)) })}</small>
          </label>
        </header>

        {update.isError && <MarketingErrorMessage error={update.error} action="write" t={t} />}
        {update.isSuccess && !dirty && <p className="studio-saved" role="status"><Check size={14} aria-hidden="true" /> {t('studio.savedNote')}</p>}

        {(platforms.length > 1 || variants.length > 1) && (
          <div className="studio-switches">
            {platforms.length > 1 && (
              <div className="apex-segmented studio-platforms" role="tablist" aria-label={t('studio.platforms')}>
                {platforms.map((p) => <button key={p} type="button" role="tab" aria-selected={platform === p} onClick={() => setPlatform(p)}>{t(`studio.result.places.${p}`, { defaultValue: PLATFORM_LABELS[p] || p })}</button>)}
              </div>
            )}
            {variants.length > 1 && (
              <div className="apex-segmented" role="group" aria-label={t('studio.platforms')}>
                {variants.map((item, index) => <button key={item.variant_index} type="button" aria-pressed={index === variantIndex} onClick={() => setVariantIndex(index)}>{t('studio.option', { n: item.variant_index })}</button>)}
              </div>
            )}
          </div>
        )}

        <div className="studio-layout">
          <div className="studio-image">
            <PostPreview platform={platform} variant={v} businessName={businessName} t={t}
              picture={<PictureFrame pictures={pictures} t={t} pendingFormat={pendingFormat} />} />
            <PictureNotes pictures={pictures} t={t} />
          </div>

          <div className="studio-copy">
            {mode === 'next' && (
              <div className="studio-panel studio-next">
                <h3>{t('studio.result.nextTitle')}</h3>
                <ol className="studio-next__steps">
                  <li>
                    <span className="studio-next__num" aria-hidden="true">1</span>
                    <div><strong>{t('studio.result.step1')}</strong><DownloadPicture pictures={pictures} t={t} />{!pictures.image.url && <p className="apex-muted">{t('studio.result.noPicture')}</p>}</div>
                  </li>
                  <li>
                    <span className="studio-next__num" aria-hidden="true">2</span>
                    <div className="studio-post"><strong>{t('studio.result.step2')}</strong><CopyText text={postText(platform, v)} t={t} /></div>
                  </li>
                  <li>
                    <span className="studio-next__num" aria-hidden="true">3</span>
                    <div><strong>{t('studio.result.step3', { place })}</strong></div>
                  </li>
                </ol>
                <div className="studio-change">
                  <h4>{t('studio.result.changeTitle')}</h4>
                  <div className="studio-change__buttons">
                    <ApexButton variant="secondary" icon={PenLine} className="studio-post__edit" onClick={() => setMode('text')}>{t('studio.result.editText')}</ApexButton>
                    <ApexButton variant="secondary" icon={ImagePlus} className="studio-new-picture" onClick={() => setMode('picture')}>{t('studio.result.newPicture')}</ApexButton>
                    {onRewrite && <ApexButton variant="ghost" icon={Sparkles} loading={rewriting} onClick={onRewrite}>{t('studio.result.newText')}</ApexButton>}
                  </div>
                </div>
              </div>
            )}

            {mode === 'text' && original && (
              <div className="studio-panel studio-post studio-edit">
                <header className="studio-panel__head">
                  <h3>{t('studio.result.editTitle')}</h3>
                  <button type="button" className="studio-close" onClick={() => setMode('next')} aria-label={t('studio.result.done')}><X size={18} /></button>
                </header>
                <p className="apex-muted">{t('studio.result.editHint')}</p>
                <label className="apex-field"><span>{t('studio.result.headline')}</span>
                  <input className="apex-input" dir="auto" value={v.headline || ''} maxLength={limits.headline || 300} onChange={(e) => setField(platform, original, 'headline', e.target.value)} />
                  {limits.headline && <small className="apex-muted">{t('studio.charsLeft', { count: limits.headline - (v.headline || '').length })}</small>}
                </label>
                <label className="apex-field"><span>{platform === 'GOOGLE_ADS' ? t('studio.result.adText') : t('studio.result.caption')}</span>
                  <textarea className="apex-input" dir="auto" rows={platform === 'GOOGLE_ADS' ? 2 : 5} value={v.body_copy || ''} maxLength={limits.body_copy || 5000} onChange={(e) => setField(platform, original, 'body_copy', e.target.value)} />
                  {limits.body_copy && <small className="apex-muted">{t('studio.charsLeft', { count: limits.body_copy - (v.body_copy || '').length })}</small>}
                </label>
                {platform !== 'GOOGLE_ADS' && (
                  <label className="apex-field"><span>{t('studio.result.hashtags')}</span>
                    <input className="apex-input" dir="auto" value={(v.hashtags || []).join(' ')} onChange={(e) => setField(platform, original, 'hashtags', hashtagsFromText(e.target.value))} />
                    <small className="apex-muted">{t('studio.result.hashtagsHint')}</small>
                  </label>
                )}
                <label className="apex-field"><span>{t('studio.result.cta')}</span>
                  <input className="apex-input" dir="auto" value={v.cta || ''} maxLength={120} onChange={(e) => setField(platform, original, 'cta', e.target.value)} />
                </label>
                <div className="studio-panel__actions">
                  {dirty ? (
                    <>
                      <ApexButton icon={Save} loading={update.isPending} onClick={save}>{t('studio.result.save')}</ApexButton>
                      <ApexButton variant="ghost" icon={RotateCcw} onClick={undo}>{t('studio.result.undo')}</ApexButton>
                    </>
                  ) : <ApexButton variant="secondary" icon={Check} onClick={() => setMode('next')}>{t('studio.result.done')}</ApexButton>}
                </div>
              </div>
            )}

            {mode === 'picture' && (
              <div className="studio-panel">
                <header className="studio-panel__head">
                  <h3>{t('studio.result.pictureTitle')}</h3>
                  <button type="button" className="studio-close" onClick={() => setMode('next')} aria-label={t('studio.result.done')}><X size={18} /></button>
                </header>
                <NewPicturePanel pictures={pictures} t={t} defaultFormat={pictures.shown?.image_format || PLATFORM_FORMAT[platform]}
                  onDone={(format) => { setPendingFormat(format); setMode('next'); }} />
              </div>
            )}

            {dirty && mode !== 'text' && (
              <div className="studio-unsaved" role="status">
                <span>{t('studio.result.unsaved')}</span>
                <ApexButton size="sm" icon={Save} loading={update.isPending} onClick={save}>{t('studio.result.save')}</ApexButton>
              </div>
            )}
          </div>
        </div>

        <PictureGallery pictures={pictures} t={t} />

        <details className="studio-fold studio-details">
          <summary>{t('studio.result.more')}</summary>
          <section className="studio-audience">
            <h3>{t('studio.result.buyers')} <Pill>{t('studio.aiSuggestion')}</Pill></h3>
            <p className="marketing-form-hint">{t('studio.result.buyersHint')}</p>
            <textarea className="apex-input" dir="auto" rows={2} maxLength={2000} value={audience} onChange={(e) => setAudience(e.target.value)} aria-label={t('studio.result.buyers')} />
          </section>
          {campaign.creative_direction && (
            <section><h3>{t('studio.result.styleNotes')}</h3><p dir="auto">{campaign.creative_direction}</p></section>
          )}
          <section><h3>{t('studio.result.photo')}</h3><p className="marketing-form-hint">{t('studio.result.photoHint')}</p>
            <ProductReferenceEditor campaign={campaign} capabilities={{ background_removal: capability?.background_removal }} t={t} />
          </section>
          <section className="studio-danger">
            {confirmDelete ? (
              <span className="studio-gallery__actions">
                <ApexButton size="sm" variant="danger" icon={Trash2} loading={remove.isPending} onClick={() => remove.mutate(id, { onSuccess: () => onDeleted?.(id) })}>{t('studio.confirmDelete')}</ApexButton>
                <ApexButton size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>{t('studio.cancel')}</ApexButton>
              </span>
            ) : <ApexButton size="sm" variant="ghost" icon={Trash2} onClick={() => setConfirmDelete(true)}>{t('studio.result.deletePost')}</ApexButton>}
            {remove.isError && <MarketingErrorMessage error={remove.error} action="write" t={t} />}
          </section>
        </details>
      </div>
    </section>
  );
}

export default CampaignEditor;

export function CampaignStatusPill({ status, t }) {
  const tone = { COMPLETED: 'success', FAILED: 'danger' }[status] || 'neutral';
  return <Pill tone={tone}>{t(`marketingApex.history.status.${status}`, { defaultValue: status })}</Pill>;
}

export function EmptyCampaign({ t }) {
  return <StateBlock compact title={t('studio.emptyTitle')} description={t('studio.emptyHint')} />;
}


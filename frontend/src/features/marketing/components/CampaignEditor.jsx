import { useEffect, useMemo, useState } from 'react';
import { Check, Copy, PenLine, Save, Sparkles, Trash2 } from 'lucide-react';
import { ApexButton, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useDeleteCampaign, useUpdateCampaign } from '../hooks/useCampaignActions.js';
import { MarketingErrorMessage } from './MarketingErrorMessage.jsx';
import { ImageStudio } from './ImageStudio.jsx';
import { ProductReferenceEditor } from './ProductReferenceEditor.jsx';

export const PLATFORM_LABELS = { INSTAGRAM: 'Instagram', FACEBOOK: 'Facebook', TIKTOK: 'TikTok', GOOGLE_ADS: 'Google Ads' };
const LIMITS = { GOOGLE_ADS: { headline: 30, body_copy: 90 } };

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
    } catch { /* clipboard refused: the text stays selectable */ }
  };
  return (
    <button type="button" className="marketing-copy-button" onClick={copy}>
      {copied ? <Check size={14} aria-hidden="true" /> : <Copy size={14} aria-hidden="true" />}{copied ? t('studio.copied') : t('studio.copyPost')}
    </button>
  );
}

function hashtagsFromText(text) {
  return (text || '').split(/[\s,،]+/).map((s) => s.trim()).filter(Boolean).map((s) => (s.startsWith('#') ? s : `#${s}`));
}

// One campaign as the customer sees and edits it: the image and the copy
// together as a post preview (older campaigns: one tab per platform). Edits are kept locally until
// "Save changes"; images in any format are made, picked and downloaded in
// ImageStudio; the whole campaign can be deleted.
export function CampaignEditor({ campaign, capability, imageFormats, assetChannels, t, locale, onDeleted, onRewrite, rewriting }) {
  const id = campaign.campaign_id;
  const platforms = Object.keys(campaign.content || {});
  const [platform, setPlatform] = useState(platforms[0]);
  const [title, setTitle] = useState(campaign.campaign_brief || '');
  const [audience, setAudience] = useState(campaign.audience_summary || '');
  const [edits, setEdits] = useState({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const update = useUpdateCampaign();
  const remove = useDeleteCampaign();
  const when = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);

  useEffect(() => {
    setTitle(campaign.campaign_brief || '');
    setAudience(campaign.audience_summary || '');
    setEdits({});
    setConfirmDelete(false);
    setPlatform((current) => (campaign.content?.[current] ? current : Object.keys(campaign.content || {})[0]));
  }, [campaign]);

  const variantKey = (p, v) => `${p}:${v.variant_index}`;
  const current = (p, v) => ({ ...v, ...(edits[variantKey(p, v)] || {}) });
  const setField = (p, v, field, value) => setEdits((all) => ({ ...all, [variantKey(p, v)]: { ...(all[variantKey(p, v)] || {}), [field]: value } }));
  const dirty = Object.keys(edits).length > 0 || title.trim() !== (campaign.campaign_brief || '') || audience !== (campaign.audience_summary || '');

  const save = () => update.mutate({
    campaignId: id,
    title: title.trim() !== (campaign.campaign_brief || '') ? title.trim() : undefined,
    audienceSummary: audience !== (campaign.audience_summary || '') ? audience : undefined,
    variants: Object.entries(edits).map(([key, fields]) => {
      const [p, index] = key.split(':');
      return { platform: p, variant_index: Number(index), ...fields };
    }),
  }, { onSuccess: () => setEdits({}) });

  const variants = campaign.content?.[platform] || [];
  return (
    <Panel
      className="studio-editor"
      eyebrow={t('studio.reviewEyebrow')}
      title={(
        <label className="studio-title">
          <PenLine size={15} aria-hidden="true" />
          <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} aria-label={t('studio.titleLabel')} dir="auto" />
        </label>
      )}
      subtitle={t('studio.savedAt', { date: when.format(new Date(campaign.updated_at || campaign.completed_at || campaign.requested_at)) })}
      actions={(
        <div className="studio-editor__actions">
          <ApexButton size="sm" icon={Save} disabled={!dirty} loading={update.isPending} onClick={save}>{dirty ? t('studio.save') : t('studio.saved')}</ApexButton>
          {onRewrite && <ApexButton size="sm" variant="ghost" icon={Sparkles} loading={rewriting} onClick={onRewrite}>{t('studio.rewrite')}</ApexButton>}
          {confirmDelete ? (
            <>
              <ApexButton size="sm" variant="danger" icon={Trash2} loading={remove.isPending} onClick={() => remove.mutate(id, { onSuccess: () => onDeleted?.(id) })}>{t('studio.confirmDelete')}</ApexButton>
              <ApexButton size="sm" variant="ghost" onClick={() => setConfirmDelete(false)}>{t('studio.cancel')}</ApexButton>
            </>
          ) : <ApexButton size="sm" variant="ghost" icon={Trash2} onClick={() => setConfirmDelete(true)}>{t('studio.delete')}</ApexButton>}
        </div>
      )}
    >
      {update.isError && <MarketingErrorMessage error={update.error} action="write" t={t} />}
      {update.isSuccess && !dirty && <p className="studio-saved" role="status"><Check size={14} aria-hidden="true" /> {t('studio.savedNote')}</p>}
      {remove.isError && <MarketingErrorMessage error={remove.error} action="write" t={t} />}

      <div className="studio-layout">
        <ImageStudio campaign={campaign} capability={capability} formats={imageFormats} channels={assetChannels} t={t} />
        <div className="studio-copy">
          {platforms.length > 1 && (
            <div className="apex-segmented studio-platforms" role="tablist" aria-label={t('studio.platforms')}>
              {platforms.map((p) => <button key={p} type="button" role="tab" aria-selected={platform === p} onClick={() => setPlatform(p)}>{PLATFORM_LABELS[p] || p}</button>)}
            </div>
          )}
          {variants.map((original) => {
            const v = current(platform, original);
            const limits = LIMITS[platform] || {};
            return (
              <article key={original.variant_index} className="studio-post">
                <header>
                  <strong>{platforms.length === 1 && variants.length === 1 ? t('studio.post') : t('studio.option', { n: original.variant_index })}</strong>
                  <CopyText text={postText(platform, v)} t={t} />
                </header>
                <label className="apex-field"><span>{t('studio.headline')}</span>
                  <input className="apex-input" dir="auto" value={v.headline || ''} maxLength={limits.headline || 300} onChange={(e) => setField(platform, original, 'headline', e.target.value)} />
                </label>
                <label className="apex-field"><span>{platform === 'GOOGLE_ADS' ? t('studio.description') : t('studio.caption')}</span>
                  <textarea className="apex-input" dir="auto" rows={platform === 'GOOGLE_ADS' ? 2 : 4} value={v.body_copy || ''} maxLength={limits.body_copy || 5000} onChange={(e) => setField(platform, original, 'body_copy', e.target.value)} />
                  {limits.body_copy && <small className="apex-muted">{t('studio.charsLeft', { count: limits.body_copy - (v.body_copy || '').length })}</small>}
                </label>
                <div className="studio-post__row">
                  {platform !== 'GOOGLE_ADS' && (
                    <label className="apex-field"><span>{t('studio.hashtags')}</span>
                      <input className="apex-input" dir="auto" value={(v.hashtags || []).join(' ')} onChange={(e) => setField(platform, original, 'hashtags', hashtagsFromText(e.target.value))} />
                    </label>
                  )}
                  <label className="apex-field"><span>{t('studio.cta')}</span>
                    <input className="apex-input" dir="auto" value={v.cta || ''} maxLength={120} onChange={(e) => setField(platform, original, 'cta', e.target.value)} />
                  </label>
                </div>
              </article>
            );
          })}
        </div>
      </div>

      <section className="studio-audience">
        <h3>{t('marketing.results.audienceTitle')} <Pill>{t('studio.aiSuggestion')}</Pill></h3>
        <p className="marketing-form-hint">{t('marketing.results.audienceNote')}</p>
        <textarea className="apex-input" dir="auto" rows={2} maxLength={2000} value={audience} onChange={(e) => setAudience(e.target.value)} aria-label={t('marketing.results.audienceTitle')} />
      </section>

      <details className="studio-more">
        <summary>{t('studio.more')}</summary>
        {campaign.creative_direction && (
          <section><h3>{t('marketing.results.creativeDirectionTitle')}</h3><p className="marketing-form-hint">{t('marketing.results.creativeDirectionNote')}</p><p dir="auto">{campaign.creative_direction}</p></section>
        )}
        <section><h3>{t('marketing.results.referenceEditorTitle')}</h3><p className="marketing-form-hint">{t('marketing.results.referenceEditorHint')}</p>
          <ProductReferenceEditor campaign={campaign} capabilities={{ background_removal: capability?.background_removal }} t={t} />
        </section>
      </details>
    </Panel>
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

import { useEffect, useState } from 'react';
import { Check, Download, ImageIcon, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { ApexButton, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useCampaignImage } from '../hooks/useCampaignImage.js';
import { useGenerateCampaignImage } from '../hooks/useGenerateCampaignImage.js';
import { useAssetImage, useCampaignAssets, useDeleteAsset, useUpdateAsset } from '../hooks/useCampaignAssets.js';
import { MarketingErrorMessage } from './MarketingErrorMessage.jsx';

// Used until GET /marketing/options answers (the server's list wins).
export const DEFAULT_IMAGE_FORMATS = [
  { key: 'SQUARE', ratio: '1:1', width: 1080, height: 1080 },
  { key: 'PORTRAIT', ratio: '4:5', width: 1080, height: 1350 },
  { key: 'STORY', ratio: '9:16', width: 1080, height: 1920 },
  { key: 'LANDSCAPE', ratio: '16:9', width: 1920, height: 1080 },
  { key: 'WIDE', ratio: '1.91:1', width: 1200, height: 628 },
];
export const DEFAULT_ASSET_CHANNELS = ['INSTAGRAM', 'FACEBOOK', 'TIKTOK', 'GOOGLE_ADS', 'WEBSITE', 'PRINT', 'OTHER'];
const EXTENSIONS = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp' };

function fileName(campaign, asset, type) {
  const base = (campaign.campaign_brief || 'campaign').replace(/[^\p{L}\p{N}]+/gu, '-').slice(0, 40);
  return `keel-${base}${asset ? `-${asset.image_format.toLowerCase()}` : ''}.${EXTENSIONS[type] || 'png'}`;
}

function aspect(asset) {
  return asset?.width && asset?.height ? `${asset.width} / ${asset.height}` : '1 / 1';
}

function GalleryItem({ campaign, asset, selected, onSelect, channels, t }) {
  const image = useAssetImage(campaign.campaign_id, asset.asset_id);
  const update = useUpdateAsset();
  const remove = useDeleteAsset();
  const [confirming, setConfirming] = useState(false);
  const formatName = t(`studio.gallery.formats.${asset.image_format}`);
  return (
    <li className={`studio-gallery__item${selected ? ' is-selected' : ''}`}>
      <button type="button" className="studio-gallery__thumb" style={{ aspectRatio: aspect(asset) }} onClick={onSelect}
        aria-pressed={selected} aria-label={t('studio.gallery.preview', { format: formatName })}>
        {image.url ? <img src={image.url} alt="" /> : image.isError ? <ImageIcon size={18} aria-hidden="true" /> : <span className="apex-spinner" aria-hidden="true" />}
      </button>
      <div className="studio-gallery__meta">
        <span className="studio-gallery__badges">
          <Pill>{formatName}</Pill>
          <Pill tone={asset.mode === 'ai' ? 'accent' : 'neutral'}>{asset.mode === 'ai' ? t('studio.gallery.aiBadge') : t('studio.gallery.designedBadge')}</Pill>
          {asset.attached && <Pill tone="success" icon={Check}>{t('studio.gallery.attached')}</Pill>}
        </span>
        <label className="studio-gallery__channel">
          <span className="sr-only">{t('studio.gallery.channelLabel')}</span>
          <select className="apex-input" value={asset.channel || ''} disabled={update.isPending}
            aria-label={t('studio.gallery.channelFor', { format: formatName })}
            onChange={(e) => update.mutate({ campaignId: campaign.campaign_id, assetId: asset.asset_id, channel: e.target.value || null })}>
            <option value="">{t('studio.gallery.channelNone')}</option>
            {channels.map((c) => <option key={c} value={c}>{t(`studio.gallery.channels.${c}`)}</option>)}
          </select>
        </label>
        <span className="studio-gallery__actions">
          {!asset.attached && (
            <ApexButton size="sm" variant="secondary" icon={Check} loading={update.isPending}
              onClick={() => update.mutate({ campaignId: campaign.campaign_id, assetId: asset.asset_id, attach: true })}>
              {t('studio.gallery.use')}
            </ApexButton>
          )}
          {image.url && (
            <a className="apex-btn apex-btn--ghost apex-btn--sm" href={image.url} download={fileName(campaign, asset, image.type)}
              aria-label={t('studio.gallery.downloadNamed', { format: formatName })}>
              <Download size={14} aria-hidden="true" />
            </a>
          )}
          {confirming ? (
            <>
              <ApexButton size="sm" variant="danger" loading={remove.isPending}
                onClick={() => remove.mutate({ campaignId: campaign.campaign_id, assetId: asset.asset_id }, { onSuccess: () => setConfirming(false) })}>
                {t('studio.gallery.confirmDelete')}
              </ApexButton>
              <ApexButton size="sm" variant="ghost" onClick={() => setConfirming(false)}>{t('studio.cancel')}</ApexButton>
            </>
          ) : (
            <ApexButton size="sm" variant="ghost" icon={Trash2} onClick={() => setConfirming(true)}
              aria-label={t('studio.gallery.deleteNamed', { format: formatName })} />
          )}
        </span>
        {(update.isError || remove.isError) && <MarketingErrorMessage error={update.error || remove.error} action="image" t={t} />}
      </div>
    </li>
  );
}

// The campaign's images: the one its post uses (or the one picked to look
// at), the options for a new one (format, where it will be used, the
// description the image model gets), and every image made so far.
export function ImageStudio({ campaign, capability, formats, channels, t }) {
  const id = campaign.campaign_id;
  const formatList = formats?.length ? formats : DEFAULT_IMAGE_FORMATS;
  const channelList = channels?.length ? channels : DEFAULT_ASSET_CHANNELS;
  const generate = useGenerateCampaignImage();
  const assets = useCampaignAssets(id);
  const list = assets.data?.assets ?? [];
  const [selectedId, setSelectedId] = useState(null);
  const [format, setFormat] = useState('SQUARE');
  const [channel, setChannel] = useState('');
  const [prompt, setPrompt] = useState(campaign.image_prompt_default || '');
  const [attach, setAttach] = useState(true);

  useEffect(() => {
    setSelectedId(null);
    setPrompt(campaign.image_prompt_default || '');
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const shown = list.find((a) => a.asset_id === selectedId) || list.find((a) => a.attached) || null;
  const preview = useAssetImage(id, shown?.asset_id);
  // A campaign image stored before the gallery existed and not (yet) listed.
  const legacy = !shown && campaign.image_generation_status === 'COMPLETED' && Boolean(campaign.generated_image_key) && assets.isSuccess;
  const legacyImage = useCampaignImage(id, 'generated', { enabled: legacy, version: campaign.generated_image_key });
  const image = shown ? preview : legacyImage;
  const result = generate.data;
  const status = result?.image_generation_status || campaign.image_generation_status;
  const aiAvailable = Boolean(capability?.available);

  const create = () => generate.mutate(
    { campaignId: id, imageFormat: format, prompt, channel: channel || undefined, attach },
    { onSuccess: (data) => { if (data?.asset?.asset_id) setSelectedId(data.asset.asset_id); } },
  );

  return (
    <div className="studio-image">
      {generate.isPending ? (
        <div className="studio-image__frame is-empty" role="status" aria-live="polite" style={{ aspectRatio: aspect(formatList.find((f) => f.key === format)) }}>
          <span className="apex-spinner" aria-hidden="true" /><p>{t('studio.creatingImage')}</p>
        </div>
      ) : shown || legacy ? (
        image.isLoading ? <div className="studio-image__frame" style={{ aspectRatio: aspect(shown) }}><span className="apex-spinner" aria-hidden="true" /></div>
          : image.url ? <img className="studio-image__frame" style={{ aspectRatio: aspect(shown) }} src={image.url} alt={t('studio.imageAlt', { title: campaign.campaign_brief })} />
            : <div className="studio-image__frame is-empty"><p>{t('marketing.results.imageLoadError')}</p></div>
      ) : (
        <div className="studio-image__frame is-empty">
          <ImageIcon size={28} aria-hidden="true" />
          <p>{campaign.image_generation_blocked ? t('studio.imageBlocked')
            : status === 'PROVIDER_ERROR' ? t('studio.imageFailed')
              : assets.isPending ? t('common.loading') : t('studio.gallery.empty')}</p>
        </div>
      )}
      {shown?.mode === 'designed' && <p className="studio-image__note">{t('studio.imageDesigned')}</p>}
      {campaign.image_generation_blocked && !shown && <MarketingErrorMessage error={{ response: { status: 402, data: { detail: campaign.image_generation_blocked } } }} action="image" t={t} />}
      {generate.isError && <MarketingErrorMessage error={generate.error} action="image" t={t} />}
      {result?.image_generation_status === 'PROVIDER_ERROR' && <p className="marketing-inline-error" role="alert">{t('studio.imageFailed')}</p>}
      {result?.image_generation_status === 'COMPLETED' && result.image_generation_mode === 'designed' && aiAvailable && (
        <p className="studio-image__note" role="status">{t('studio.gallery.fellBackToDesigned')}</p>
      )}
      {image.url && (
        <div className="studio-image__actions">
          <a className="apex-btn apex-btn--secondary apex-btn--sm" href={image.url} download={fileName(campaign, shown, image.type)}>
            <Download size={14} aria-hidden="true" />{t('marketing.results.downloadImage')}
          </a>
        </div>
      )}

      <fieldset className="studio-image__options">
        <legend>{t('studio.gallery.newImage')}</legend>
        <div className="studio-formats" role="radiogroup" aria-label={t('studio.gallery.formatLabel')}>
          {formatList.map((f) => (
            <button key={f.key} type="button" role="radio" aria-checked={format === f.key} className="studio-format" onClick={() => setFormat(f.key)}>
              <span className="studio-format__shape" style={{ aspectRatio: `${f.width} / ${f.height}` }} aria-hidden="true" />
              <span>{t(`studio.gallery.formats.${f.key}`)}</span>
            </button>
          ))}
        </div>
        <label className="apex-field"><span>{t('studio.gallery.channelLabel')}</span>
          <select className="apex-input" value={channel} onChange={(e) => setChannel(e.target.value)}>
            <option value="">{t('studio.gallery.channelNone')}</option>
            {channelList.map((c) => <option key={c} value={c}>{t(`studio.gallery.channels.${c}`)}</option>)}
          </select>
        </label>
        {aiAvailable ? (
          <label className="apex-field"><span>{t('studio.gallery.promptLabel')}</span>
            <textarea className="apex-input" dir="ltr" rows={3} maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            <small className="apex-muted">{t('studio.gallery.promptHint')}</small>
            {prompt !== (campaign.image_prompt_default || '') && (
              <button type="button" className="marketing-copy-button" onClick={() => setPrompt(campaign.image_prompt_default || '')}>
                <RotateCcw size={13} aria-hidden="true" />{t('studio.gallery.resetPrompt')}
              </button>
            )}
          </label>
        ) : <p className="apex-muted studio-note">{t('studio.gallery.designedOnly')}</p>}
        {list.length > 0 && (
          <label className="studio-check"><input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} />{t('studio.gallery.attachNew')}</label>
        )}
        <ApexButton size="sm" icon={RefreshCw} loading={generate.isPending} onClick={create}>
          {aiAvailable ? t('studio.gallery.create') : t('studio.gallery.createDesigned')}
        </ApexButton>
        {capability?.external && <p className="apex-muted studio-note">{t('studio.imagePrivacy')}</p>}
      </fieldset>

      <section className="studio-gallery" aria-label={t('studio.gallery.title')}>
        <h3>{t('studio.gallery.title')}{list.length > 0 && <small className="apex-muted"> · {t('studio.gallery.count', { count: list.length })}</small>}</h3>
        {assets.isPending ? <StateBlock kind="loading" compact title={t('common.loading')} />
          : assets.isError ? <StateBlock kind="error" compact title={t('studio.gallery.loadError')} onRetry={() => assets.refetch()} retryLabel={t('demandApex.actions.retry')} />
            : list.length === 0 ? <p className="apex-muted">{t('studio.gallery.empty')}</p>
              : (
                <ul className="studio-gallery__list">
                  {list.map((asset) => (
                    <GalleryItem key={asset.asset_id} campaign={campaign} asset={asset} channels={channelList} t={t}
                      selected={shown?.asset_id === asset.asset_id} onSelect={() => setSelectedId(asset.asset_id)} />
                  ))}
                </ul>
              )}
      </section>
    </div>
  );
}

export default ImageStudio;

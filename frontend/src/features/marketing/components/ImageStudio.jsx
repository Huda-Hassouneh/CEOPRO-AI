import { useEffect, useState } from 'react';
import { Check, Download, ImageIcon, Layers, RefreshCw, RotateCcw, Trash2, Wand2, XCircle } from 'lucide-react';
import { ApexButton, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useCampaignImage } from '../hooks/useCampaignImage.js';
import { useGenerateCampaignImage } from '../hooks/useGenerateCampaignImage.js';
import { useAssetImage, useCampaignAssets, useDeleteAsset, useUpdateAsset } from '../hooks/useCampaignAssets.js';
import { useCancelImageJobs, useImageCapacity, useImageJobs, useQueueImageBatch, useRetryImageJobs } from '../hooks/useImageJobs.js';
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

// ASCII only: browsers replace a download name with non-Latin letters (an
// Arabic title) by a bare "download" (seen in Chrome). The asset id keeps
// several images of one campaign apart.
function fileName(campaign, asset, type) {
  const base = (campaign.campaign_brief || '').replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'campaign';
  const suffix = asset ? `-${asset.image_format.toLowerCase()}-${asset.asset_id.slice(0, 8)}` : '';
  return `keel-${base}${suffix}.${EXTENSIONS[type] || 'png'}`;
}

export function aspect(asset) {
  return asset?.width && asset?.height ? `${asset.width} / ${asset.height}` : '1 / 1';
}

// Everything about a campaign's pictures, shared by the post preview, the
// "try a different picture" panel and the picture list: the one shown (the
// one picked to look at, else the one the post uses), the gallery, the
// background queue and the create action.
export function useCampaignPictures({ campaign, capability, formats, channels }) {
  const id = campaign.campaign_id;
  const formatList = formats?.length ? formats : DEFAULT_IMAGE_FORMATS;
  const channelList = channels?.length ? channels : DEFAULT_ASSET_CHANNELS;
  const generate = useGenerateCampaignImage();
  const assets = useCampaignAssets(id);
  const list = assets.data?.assets ?? [];
  const [selectedId, setSelectedId] = useState(null);
  useEffect(() => { setSelectedId(null); }, [id]);

  const shown = list.find((a) => a.asset_id === selectedId) || list.find((a) => a.attached) || null;
  const preview = useAssetImage(id, shown?.asset_id);
  // A campaign image stored before the gallery existed and not (yet) listed.
  const legacy = !shown && campaign.image_generation_status === 'COMPLETED' && Boolean(campaign.generated_image_key) && assets.isSuccess;
  const legacyImage = useCampaignImage(id, 'generated', { enabled: legacy, version: campaign.generated_image_key });
  const image = shown ? preview : legacyImage;
  const aiAvailable = Boolean(capability?.available);
  // A live background worker: new images go through its queue, so the page never waits minutes.
  const capacity = useImageCapacity();
  const queued = Boolean(capacity.data?.available);
  const jobs = useImageJobs(id);
  const queueOne = useQueueImageBatch();
  const counts = jobs.data?.counts;
  const making = counts ? counts.QUEUED + counts.RUNNING : 0;

  const create = ({ format, prompt, channel, attach }) => (queued
    ? queueOne.mutate({ campaignId: id, formats: [format], variations: 1, prompt, channel: channel || undefined, attachFirst: attach || !list.length })
    : generate.mutate(
      { campaignId: id, imageFormat: format, prompt, channel: channel || undefined, attach },
      { onSuccess: (data) => { if (data?.asset?.asset_id) setSelectedId(data.asset.asset_id); } },
    ));

  return {
    campaign, capability, formatList, channelList, generate, assets, list, shown, setSelectedId, legacy, image,
    aiAvailable, capacity, queued, jobs, queueOne, making, create, busy: generate.isPending || queueOne.isPending,
  };
}

// The picture as it appears in the post preview, with its loading,
// in-progress, blocked and failed states.
export function PictureFrame({ pictures, t, pendingFormat }) {
  const { campaign, generate, shown, legacy, image, making, assets, formatList } = pictures;
  const status = generate.data?.image_generation_status || campaign.image_generation_status;
  if (generate.isPending || (making > 0 && !shown)) {
    return (
      <div className="studio-image__frame is-empty" role="status" aria-live="polite" style={{ aspectRatio: aspect(formatList.find((f) => f.key === pendingFormat)) }}>
        <span className="apex-spinner" aria-hidden="true" /><p>{t('studio.result.making')}</p>
      </div>
    );
  }
  if (shown || legacy) {
    if (image.isLoading) return <div className="studio-image__frame is-empty" style={{ aspectRatio: aspect(shown) }}><span className="apex-spinner" aria-hidden="true" /></div>;
    if (image.url) return <img className="studio-image__frame" style={{ aspectRatio: aspect(shown) }} src={image.url} alt={t('studio.imageAlt', { title: campaign.campaign_brief })} />;
    return <div className="studio-image__frame is-empty"><p>{t('marketing.results.imageLoadError')}</p></div>;
  }
  return (
    <div className="studio-image__frame is-empty">
      <ImageIcon size={28} aria-hidden="true" />
      <p>{campaign.image_generation_blocked ? t('studio.imageBlocked')
        : status === 'PROVIDER_ERROR' ? t('studio.imageFailed')
          : assets.isPending ? t('common.loading') : t('studio.result.noPicture')}</p>
    </div>
  );
}

export function DownloadPicture({ pictures, t, className = '' }) {
  const { campaign, shown, image } = pictures;
  if (!image.url) return null;
  return (
    <a className={`apex-btn apex-btn--secondary studio-download ${className}`.trim()} href={image.url} download={fileName(campaign, shown, image.type)}>
      <Download size={16} aria-hidden="true" />{t('studio.result.download')}
    </a>
  );
}

// Notes and errors about the picture that belong next to it.
export function PictureNotes({ pictures, t }) {
  const { campaign, shown, generate, aiAvailable } = pictures;
  const result = generate.data;
  return (
    <>
      {shown?.mode === 'designed' && <p className="studio-image__note">{t('studio.result.layoutNote')}</p>}
      {campaign.image_generation_blocked && !shown && <MarketingErrorMessage error={{ response: { status: 402, data: { detail: campaign.image_generation_blocked } } }} action="image" t={t} />}
      {generate.isError && <MarketingErrorMessage error={generate.error} action="image" t={t} />}
      {result?.image_generation_status === 'PROVIDER_ERROR' && <p className="marketing-inline-error" role="alert">{t('studio.imageFailed')}</p>}
      {result?.image_generation_status === 'COMPLETED' && result.image_generation_mode === 'designed' && aiAvailable && !shown && (
        <p className="studio-image__note" role="status">{t('studio.result.layoutNote')}</p>
      )}
    </>
  );
}

// Shape choice with a drawn outline and plain names (no ratios).
export function ShapePicker({ formats, value, onChange, t, label }) {
  return (
    <div className="studio-formats" role="radiogroup" aria-label={label}>
      {formats.map((f) => (
        <button key={f.key} type="button" role="radio" aria-checked={value === f.key} className="studio-format" onClick={() => onChange(f.key)}>
          <span className="studio-format__shape" style={{ aspectRatio: `${f.width} / ${f.height}` }} aria-hidden="true" />
          <strong>{t(`studio.formatsPlain.${f.key}.title`)}</strong>
          <small>{t(`studio.formatsPlain.${f.key}.hint`)}</small>
        </button>
      ))}
    </div>
  );
}

// "Try a different picture": shape (defaulting to the post's current one),
// an optional description, and one button. Where the picture will be used
// and making many at once are folded under "More options".
export function NewPicturePanel({ pictures, t, defaultFormat, onDone }) {
  const { campaign, capability, formatList, channelList, list, aiAvailable, queued, making, queueOne, create, busy, capacity, jobs } = pictures;
  const [format, setFormat] = useState(defaultFormat || 'SQUARE');
  const [channel, setChannel] = useState('');
  const [prompt, setPrompt] = useState(campaign.image_prompt_default || '');
  const [attach, setAttach] = useState(true);
  useEffect(() => { setPrompt(campaign.image_prompt_default || ''); }, [campaign.campaign_id]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="studio-panel studio-picture-panel">
      <fieldset className="studio-image__options">
        <legend className="sr-only">{t('studio.result.pictureTitle')}</legend>
        <div className="apex-field"><span>{t('studio.result.shape')}</span>
          <ShapePicker formats={formatList} value={format} onChange={setFormat} t={t} label={t('studio.result.shape')} />
        </div>
        {aiAvailable ? (
          <label className="apex-field"><span>{t('studio.result.describe')}</span>
            <textarea className="apex-input" dir="auto" rows={3} maxLength={2000} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
            <small className="apex-muted">{t('studio.result.describeHint')}</small>
            {prompt !== (campaign.image_prompt_default || '') && (
              <button type="button" className="marketing-copy-button" onClick={() => setPrompt(campaign.image_prompt_default || '')}>
                <RotateCcw size={13} aria-hidden="true" />{t('studio.result.resetDescribe')}
              </button>
            )}
          </label>
        ) : <p className="apex-muted studio-note">{t('studio.result.layoutOnly')}</p>}
        {list.length > 0 && (
          <label className="studio-check"><input type="checkbox" checked={attach} onChange={(e) => setAttach(e.target.checked)} />{t('studio.result.useNew')}</label>
        )}
        <div className="studio-panel__actions">
          <ApexButton icon={RefreshCw} loading={busy} onClick={() => { create({ format, prompt, channel, attach }); onDone?.(format); }}>
            {t('studio.result.makePicture')}
          </ApexButton>
        </div>
        {queued && making > 0 && <p className="apex-muted studio-note" role="status">{t('studio.batch.making', { count: making })}</p>}
        {queueOne.isError && <MarketingErrorMessage error={queueOne.error} action="image" t={t} />}
        {capability?.external && <p className="apex-muted studio-note">{t('studio.wizard.privacy')}</p>}
        <details className="studio-fold">
          <summary>{t('studio.result.more')}</summary>
          <label className="apex-field"><span>{t('studio.result.forLabel')}</span>
            <select className="apex-input" value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="">{t('studio.gallery.channelNone')}</option>
              {channelList.map((c) => <option key={c} value={c}>{t(`studio.gallery.channels.${c}`)}</option>)}
            </select>
          </label>
        </details>
      </fieldset>
      {queued && aiAvailable && (
        <BatchPanel campaign={campaign} formatList={formatList} channel={channel} prompt={prompt} capacity={capacity.data} jobs={jobs} t={t} />
      )}
    </div>
  );
}

function GalleryItem({ campaign, asset, selected, onSelect, channels, t }) {
  const image = useAssetImage(campaign.campaign_id, asset.asset_id);
  const update = useUpdateAsset();
  const remove = useDeleteAsset();
  const [confirming, setConfirming] = useState(false);
  const formatName = t(`studio.formatsPlain.${asset.image_format}.title`);
  return (
    <li className={`studio-gallery__item${selected ? ' is-selected' : ''}`}>
      <button type="button" className="studio-gallery__thumb" style={{ aspectRatio: aspect(asset) }} onClick={onSelect}
        aria-pressed={selected} aria-label={t('studio.gallery.preview', { format: formatName })}>
        {image.url ? <img src={image.url} alt="" /> : image.isError ? <ImageIcon size={18} aria-hidden="true" /> : <span className="apex-spinner" aria-hidden="true" />}
      </button>
      <div className="studio-gallery__meta">
        <span className="studio-gallery__badges">
          <Pill>{formatName}</Pill>
          <Pill tone={asset.mode === 'ai' ? 'accent' : 'neutral'}>{asset.mode === 'ai' ? t('studio.result.madeAuto') : t('studio.result.madeLayout')}</Pill>
          {asset.attached && <Pill tone="success" icon={Check}>{t('studio.result.inUse')}</Pill>}
        </span>
        <span className="studio-gallery__actions">
          {!asset.attached && (
            <ApexButton size="sm" variant="secondary" icon={Check} loading={update.isPending}
              onClick={() => update.mutate({ campaignId: campaign.campaign_id, assetId: asset.asset_id, attach: true })}>
              {t('studio.result.usePicture')}
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
        <label className="studio-gallery__channel">
          <span>{t('studio.result.forLabel')}</span>
          <select className="apex-input" value={asset.channel || ''} disabled={update.isPending}
            aria-label={t('studio.gallery.channelFor', { format: formatName })}
            onChange={(e) => update.mutate({ campaignId: campaign.campaign_id, assetId: asset.asset_id, channel: e.target.value || null })}>
            <option value="">{t('studio.gallery.channelNone')}</option>
            {channels.map((c) => <option key={c} value={c}>{t(`studio.gallery.channels.${c}`)}</option>)}
          </select>
        </label>
        {(update.isError || remove.isError) && <MarketingErrorMessage error={update.error || remove.error} action="image" t={t} />}
      </div>
    </li>
  );
}

// Every picture made for the post. Folded away while there is only one
// (it is already in the preview); open as soon as there is a choice.
export function PictureGallery({ pictures, t }) {
  const { campaign, assets, list, shown, setSelectedId, channelList } = pictures;
  const [open, setOpen] = useState(list.length > 1);
  useEffect(() => { if (list.length > 1) setOpen(true); }, [list.length]);
  if (!assets.isError && list.length === 0) return null;
  return (
    <details className="studio-fold studio-gallery" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary><Layers size={15} aria-hidden="true" />{t('studio.result.pictures', { count: list.length })}</summary>
      {assets.isError ? <StateBlock kind="error" compact title={t('studio.gallery.loadError')} onRetry={() => assets.refetch()} retryLabel={t('demandApex.actions.retry')} />
        : (
          <ul className="studio-gallery__list">
            {list.map((asset) => (
              <GalleryItem key={asset.asset_id} campaign={campaign} asset={asset} channels={channelList} t={t}
                selected={shown?.asset_id === asset.asset_id} onSelect={() => setSelectedId(asset.asset_id)} />
            ))}
          </ul>
        )}
    </details>
  );
}

// Many images at once (formats x variations), made by the background image
// worker: progress, an estimate from the measured speed, cancel and retry.
function BatchPanel({ campaign, formatList, channel, prompt, capacity, jobs, t }) {
  const id = campaign.campaign_id;
  const [formats, setFormats] = useState(['SQUARE']);
  const [variations, setVariations] = useState(4);
  const queue = useQueueImageBatch();
  const cancel = useCancelImageJobs();
  const retry = useRetryImageJobs();
  const counts = jobs.data?.counts;
  const max = capacity?.batch_max || 200;
  const perFormat = Math.max(1, Math.floor(max / Math.max(1, formats.length)));
  const total = formats.length * Math.min(variations || 0, perFormat);
  const perImage = capacity?.average_seconds_per_image;
  const servers = Math.max(1, capacity?.image_servers || 1);
  const minutes = perImage ? Math.max(1, Math.round((total * perImage) / servers / 60)) : null;
  const finished = counts ? counts.COMPLETED + counts.FAILED + counts.CANCELLED : 0;
  const active = counts ? counts.QUEUED + counts.RUNNING : 0;
  const toggle = (key) => setFormats((all) => (all.includes(key) ? all.filter((k) => k !== key) : [...all, key]));

  return (
    <details className="studio-fold">
      <summary><Layers size={15} aria-hidden="true" />{t('studio.batch.title')}</summary>
      <fieldset className="studio-image__options studio-batch">
        <legend className="sr-only">{t('studio.batch.title')}</legend>
        <p className="apex-muted studio-note">{t('studio.batch.hint')}</p>
        <div className="studio-batch__formats" role="group" aria-label={t('studio.result.shape')}>
          {formatList.map((f) => (
            <label key={f.key} className="studio-check">
              <input type="checkbox" checked={formats.includes(f.key)} onChange={() => toggle(f.key)} />{t(`studio.formatsPlain.${f.key}.title`)}
            </label>
          ))}
        </div>
        <label className="apex-field"><span>{t('studio.batch.variations')}</span>
          <input className="apex-input" type="number" min={1} max={perFormat} value={variations}
            onChange={(e) => setVariations(Math.max(1, Math.min(perFormat, Number(e.target.value) || 1)))} />
        </label>
        <p className="studio-batch__summary" role="status">
          {t('studio.batch.summary', { count: total })}
          {minutes ? ` · ${t('studio.batch.estimate', { minutes })}` : ''}
        </p>
        <ApexButton size="sm" icon={Wand2} disabled={!formats.length || !total} loading={queue.isPending}
          onClick={() => queue.mutate({ campaignId: id, formats, variations: Math.min(variations, perFormat), prompt, channel: channel || undefined })}>
          {t('studio.batch.queue', { count: total })}
        </ApexButton>
        {queue.isError && (queue.error?.response?.status === 429
          ? <p className="marketing-inline-error" role="alert">{t('studio.batch.limit', { limit: queue.error.response.data?.detail?.limit ?? max })}</p>
          : <MarketingErrorMessage error={queue.error} action="image" t={t} />)}
        {counts && counts.QUEUED + counts.RUNNING + counts.COMPLETED + counts.FAILED > 0 && (
          <div className="studio-batch__progress">
            <progress max={Math.max(1, finished + active)} value={finished} aria-label={t('studio.batch.progressLabel')} />
            <p>{t('studio.batch.progress', { done: counts.COMPLETED, running: counts.RUNNING, waiting: counts.QUEUED, failed: counts.FAILED })}</p>
            <span className="studio-gallery__actions">
              {counts.QUEUED > 0 && <ApexButton size="sm" variant="ghost" icon={XCircle} loading={cancel.isPending} onClick={() => cancel.mutate(id)}>{t('studio.batch.cancel')}</ApexButton>}
              {counts.FAILED > 0 && <ApexButton size="sm" variant="secondary" icon={RefreshCw} loading={retry.isPending} onClick={() => retry.mutate(id)}>{t('studio.batch.retry')}</ApexButton>}
            </span>
            {counts.FAILED > 0 && jobs.data.jobs.find((j) => j.status === 'FAILED')?.error && (
              <p className="apex-muted studio-note">{t('studio.batch.lastError')}: {jobs.data.jobs.find((j) => j.status === 'FAILED').error}</p>
            )}
          </div>
        )}
      </fieldset>
    </details>
  );
}

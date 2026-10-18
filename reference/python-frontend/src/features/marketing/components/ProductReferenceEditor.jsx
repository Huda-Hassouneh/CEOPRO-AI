import { useState } from 'react';
import { Eraser, ImageIcon, RotateCcw, Target } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { useUploadCampaignImage } from '../hooks/useUploadCampaignImage.js';
import { useRemoveBackground } from '../hooks/useRemoveBackground.js';
import { useSetReferenceSelection } from '../hooks/useSetReferenceSelection.js';
import { useCampaignImage } from '../hooks/useCampaignImage.js';
import { MarketingErrorMessage } from './MarketingErrorMessage.jsx';
import { PhotoPicker } from './PhotoPicker.jsx';

const SELECTION_LABEL_KEY = { ORIGINAL: 'marketing.results.referenceOriginal', PROCESSED: 'marketing.results.previewProcessed' };

/**
 * Upload -> remove background (optional, provider-gated) -> preview
 * original vs. background-removed -> pick one as this campaign's product
 * reference. Never deletes the original upload - removing the background
 * only ever adds a second, separate stored image (source_image_processed_key),
 * and every state here is derived from real backend fields/mutation
 * results, never assumed.
 */
export function ProductReferenceEditor({ campaign, capabilities, t }) {
  const [imageFile, setImageFile] = useState(null);
  const [previewChoice, setPreviewChoice] = useState('original');
  const uploadImage = useUploadCampaignImage();
  const removeBackground = useRemoveBackground();
  const setReferenceSelection = useSetReferenceSelection();

  const sourceImageKey = uploadImage.data?.source_image_key ?? campaign.source_image_key;
  const processedImageKey = removeBackground.data?.source_image_processed_key ?? campaign.source_image_processed_key;
  const backgroundRemovalStatus = removeBackground.data?.background_removal_status ?? campaign.background_removal_status;
  const referenceSelection = setReferenceSelection.isSuccess
    ? setReferenceSelection.data.reference_image_selection
    : campaign.reference_image_selection;

  const previewKind = previewChoice === 'processed' ? 'processed' : 'source';
  const previewKey = previewChoice === 'processed' ? processedImageKey : sourceImageKey;
  const { url: previewUrl, isLoading: previewLoading, isError: previewError } = useCampaignImage(
    campaign.campaign_id, previewKind, { enabled: Boolean(previewKey), version: previewKey },
  );

  const handleImageUpload = () => {
    if (!imageFile) return;
    uploadImage.mutate({ campaignId: campaign.campaign_id, file: imageFile }, { onSuccess: () => setImageFile(null) });
  };

  const handleRemoveBackground = () => {
    removeBackground.mutate(campaign.campaign_id, {
      onSuccess: (data) => { if (data.background_removal_status === 'COMPLETED') setPreviewChoice('processed'); },
    });
  };

  const handleUseAsReference = () => {
    setReferenceSelection.mutate({ campaignId: campaign.campaign_id, selection: previewChoice === 'processed' ? 'PROCESSED' : 'ORIGINAL' });
  };

  const backgroundRemovalCapability = capabilities?.background_removal;

  return (
    <div className="marketing-reference-editor">
      <div className="marketing-image-upload">
        <span className="marketing-image-upload-label">{t('marketing.results.uploadImageLabel')}</span>
        <div className="marketing-image-upload__row">
          <PhotoPicker file={imageFile} onChange={(file) => { setImageFile(file); uploadImage.reset(); }} t={t} />
          {imageFile && (
            <Button size="sm" variant="outline" onClick={handleImageUpload} disabled={uploadImage.isPending} loading={uploadImage.isPending}>
              {t('marketing.results.uploadImageButton')}
            </Button>
          )}
        </div>
        {uploadImage.isError && <MarketingErrorMessage error={uploadImage.error} action="upload" t={t} />}
      </div>

      {sourceImageKey && (
        <div className="marketing-reference-editor__body">
          <div className="marketing-reference-editor__preview">
            {previewLoading ? (
              <Skeleton width="240px" height="180px" variant="rectangular" />
            ) : previewUrl ? (
              <img className="marketing-reference-editor__preview-image" src={previewUrl} alt={t(SELECTION_LABEL_KEY[previewChoice === 'processed' ? 'PROCESSED' : 'ORIGINAL'])} />
            ) : previewError ? (
              <p className="marketing-inline-error" role="alert">{t('marketing.results.imageLoadError')}</p>
            ) : null}
          </div>

          <div className="marketing-reference-editor__toggle" role="group" aria-label={t('marketing.results.referencePreviewToggle')}>
            <button
              type="button" className={`marketing-mode-tab ${previewChoice === 'original' ? 'is-active' : ''}`}
              onClick={() => setPreviewChoice('original')}
            >
              {t('marketing.results.referenceOriginal')}
            </button>
            <button
              type="button" className={`marketing-mode-tab ${previewChoice === 'processed' ? 'is-active' : ''}`}
              onClick={() => setPreviewChoice('processed')} disabled={!processedImageKey}
            >
              {t('marketing.results.previewProcessed')}
            </button>
          </div>

          <div className="marketing-reference-editor__actions">
            {backgroundRemovalCapability?.available ? (
              <Button
                size="sm" variant="outline" leadingIcon={<Eraser size={15} />}
                onClick={handleRemoveBackground} disabled={removeBackground.isPending} loading={removeBackground.isPending}
              >
                {t('marketing.results.removeBackground')}
              </Button>
            ) : (
              backgroundRemovalStatus !== 'COMPLETED' && (
                <p className="marketing-not-available">{t('marketing.results.backgroundRemovalNotConfigured')}</p>
              )
            )}

            {previewChoice === 'processed' && (
              <Button size="sm" variant="ghost" leadingIcon={<RotateCcw size={15} />} onClick={() => setPreviewChoice('original')}>
                {t('marketing.results.restoreOriginal')}
              </Button>
            )}

            <Button
              size="sm" variant="primary" leadingIcon={<Target size={15} />}
              onClick={handleUseAsReference} disabled={!previewKey || setReferenceSelection.isPending} loading={setReferenceSelection.isPending}
            >
              {t('marketing.results.useAsReference')}
            </Button>
          </div>

          {/* The backend's error text is meant for operators (provider details,
              configuration names) and is English-only; customers get the
              localized explanation. */}
          {backgroundRemovalStatus === 'PROVIDER_ERROR' && (
            <p className="marketing-inline-error" role="alert">{t('marketing.results.backgroundRemovalError')}</p>
          )}


          {removeBackground.isError && <MarketingErrorMessage error={removeBackground.error} action="photo" t={t} />}
          {setReferenceSelection.isError && <MarketingErrorMessage error={setReferenceSelection.error} action="photo" t={t} />}

          {referenceSelection && (
            <p className="marketing-reference-editor__selection">
              <ImageIcon size={13} /> {t('marketing.results.referenceCurrentlySet', { choice: t(SELECTION_LABEL_KEY[referenceSelection]) })}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

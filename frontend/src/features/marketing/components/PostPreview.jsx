import { Bookmark, Globe, Heart, MessageCircle, Send } from 'lucide-react';

// How the post will look where it is published: a feed post (Instagram,
// Facebook, TikTok) or a search/display ad (Google Ads). A preview only -
// nothing is published from here.
export function PostPreview({ platform, variant, picture, businessName, t }) {
  const name = businessName || t('studio.result.yourBusiness');
  const initial = name.trim().charAt(0).toLocaleUpperCase() || 'K';
  const place = t(`studio.result.places.${platform}`, { defaultValue: platform });

  if (platform === 'GOOGLE_ADS') {
    return (
      <figure className="studio-preview studio-preview--ad" aria-label={t('studio.result.previewLabel')}>
        <div className="studio-preview__media">{picture}</div>
        <figcaption className="studio-preview__ad">
          <span className="studio-preview__sponsor"><Globe size={13} aria-hidden="true" /><strong>{t('studio.result.sponsored')}</strong> · {name}</span>
          {variant.headline && <span className="studio-preview__ad-title" dir="auto">{variant.headline}</span>}
          {variant.body_copy && <span className="studio-preview__ad-text" dir="auto">{variant.body_copy}</span>}
          {variant.cta && <span className="studio-preview__cta" dir="auto">{variant.cta}</span>}
        </figcaption>
      </figure>
    );
  }

  return (
    <figure className={`studio-preview studio-preview--${platform.toLowerCase()}`} aria-label={t('studio.result.previewLabel')}>
      <header className="studio-preview__head">
        <span className="studio-preview__avatar" aria-hidden="true">{initial}</span>
        <span className="studio-preview__who"><strong dir="auto">{name}</strong><small>{place}</small></span>
      </header>
      <div className="studio-preview__media">{picture}</div>
      <div className="studio-preview__icons" aria-hidden="true">
        <Heart size={20} /><MessageCircle size={20} /><Send size={20} /><Bookmark size={20} className="studio-preview__save" />
      </div>
      <figcaption className="studio-preview__caption" dir="auto">
        {variant.headline && <strong className="studio-post__headline" dir="auto">{variant.headline}</strong>}
        {variant.body_copy && <span className="studio-post__body" dir="auto">{variant.body_copy}</span>}
        {variant.hashtags?.length > 0 && <span className="studio-post__tags" dir="auto">{variant.hashtags.join(' ')}</span>}
        {variant.cta && <span className="studio-preview__cta" dir="auto">{variant.cta}</span>}
        {!variant.headline && !variant.body_copy && <span className="apex-muted">{t('studio.simple.emptyField')}</span>}
      </figcaption>
    </figure>
  );
}

export default PostPreview;

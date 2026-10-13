import { ImagePlus, X } from 'lucide-react';

export const PHOTO_TYPES = 'image/png,image/jpeg,image/webp';

// A translated "Add photo" button in place of the browser's own file input
// (whose "Choose File / No file chosen" text follows the browser's
// language, not KEEL's). The input stays focusable for keyboard users.
export function PhotoPicker({ file, onChange, t }) {
  if (file) {
    return (
      <span className="mk-photo__file">
        <ImagePlus size={15} aria-hidden="true" />{file.name}
        <button type="button" onClick={() => onChange(null)} aria-label={t('marketingApex.what.removePhoto')}><X size={14} /></button>
      </span>
    );
  }
  return (
    <label className="apex-btn apex-btn--secondary apex-btn--sm mk-photo-picker">
      <ImagePlus size={14} aria-hidden="true" />{t('marketingApex.what.addPhoto')}
      <input
        type="file" accept={PHOTO_TYPES} className="sr-only"
        onChange={(e) => { onChange(e.target.files?.[0] || null); e.target.value = ''; }}
      />
    </label>
  );
}

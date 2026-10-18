const BRAND_ASSET_ROOT = '/assets/brands';

const FILE_TYPE_ASSETS = Object.freeze({
  excel: { src: `${BRAND_ASSET_ROOT}/excel.svg`, className: 'is-excel', labelKey: 'common.fileTypes.excel' },
  csv: { src: `${BRAND_ASSET_ROOT}/csv.svg`, className: 'is-csv', labelKey: 'common.fileTypes.csv' },
  pdf: { src: `${BRAND_ASSET_ROOT}/pdf.svg`, className: 'is-pdf', labelKey: 'common.fileTypes.pdf' },
  word: { src: `${BRAND_ASSET_ROOT}/word.svg`, className: 'is-word', labelKey: 'common.fileTypes.word' },
  text: { src: `${BRAND_ASSET_ROOT}/text-file.svg`, className: 'is-text', labelKey: 'common.fileTypes.text' },
  image: { src: `${BRAND_ASSET_ROOT}/image-file.svg`, className: 'is-image', labelKey: 'common.fileTypes.image' },
  generic: { src: `${BRAND_ASSET_ROOT}/text-file.svg`, className: 'is-generic', labelKey: 'common.fileTypes.generic' },
});

export function getFileTypeAsset(fileName = '') {
  const extension = fileName.toLowerCase().split('.').pop();
  if (['xlsx', 'xls'].includes(extension)) return FILE_TYPE_ASSETS.excel;
  if (extension === 'csv') return FILE_TYPE_ASSETS.csv;
  if (extension === 'pdf') return FILE_TYPE_ASSETS.pdf;
  if (['doc', 'docx'].includes(extension)) return FILE_TYPE_ASSETS.word;
  if (extension === 'txt') return FILE_TYPE_ASSETS.text;
  if (['png', 'jpg', 'jpeg'].includes(extension)) return FILE_TYPE_ASSETS.image;
  return FILE_TYPE_ASSETS.generic;
}

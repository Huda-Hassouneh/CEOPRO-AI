const BRAND_ASSET_ROOT = '/assets/brands';

const FILE_TYPE_ASSETS = Object.freeze({
  excel: { src: `${BRAND_ASSET_ROOT}/excel.svg`, className: 'is-excel', label: 'Excel' },
  csv: { src: `${BRAND_ASSET_ROOT}/csv.svg`, className: 'is-csv', label: 'CSV' },
  pdf: { src: `${BRAND_ASSET_ROOT}/pdf.svg`, className: 'is-pdf', label: 'PDF' },
  word: { src: `${BRAND_ASSET_ROOT}/word.svg`, className: 'is-word', label: 'Word' },
  text: { src: `${BRAND_ASSET_ROOT}/text-file.svg`, className: 'is-text', label: 'Text' },
  image: { src: `${BRAND_ASSET_ROOT}/image-file.svg`, className: 'is-image', label: 'Image' },
  generic: { src: `${BRAND_ASSET_ROOT}/text-file.svg`, className: 'is-generic', label: 'File' },
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

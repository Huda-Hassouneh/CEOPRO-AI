import { createElement } from 'react';
import { pdf } from '@react-pdf/renderer';
import { DemandPredictionPdfDocument } from '../pdf/DemandPredictionPdfDocument.jsx';

export async function exportDemandPredictionPdf({ data, locale, isCurrent = () => true }) {
  if (!data?.filters || !isCurrent()) return;
  const generatedAt = new Date();
  const blob = await pdf(createElement(DemandPredictionPdfDocument, { data, locale, generatedAt })).toBlob();
  if (!isCurrent()) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `KEEL-Demand-Prediction-${data.product ? 'product' : 'overview'}-${generatedAt.toISOString().slice(0, 10)}.pdf`;
  try { document.body.appendChild(link); link.click(); }
  finally { link.remove(); window.setTimeout(() => URL.revokeObjectURL(url), 60_000); }
}

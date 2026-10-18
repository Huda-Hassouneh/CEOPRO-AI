import { useEffect, useRef, useState } from 'react';

export function useDemandPdfExport({ data, locale, scope, enabled }) {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const current = useRef();
  const active = useRef(false);
  const mounted = useRef(true);
  current.current = { data, locale, scope, enabled };
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const requestExport = async () => {
    if (active.current || !enabled || !data) return;
    const snapshot = current.current;
    const isCurrent = () => mounted.current && current.current.enabled && current.current.data === snapshot.data && current.current.scope === snapshot.scope && current.current.locale === snapshot.locale;
    active.current = true;
    setExporting(true);
    setExportError(false);
    try {
      const { exportDemandPredictionPdf } = await import('../utils/exportDemandPredictionPdf.js');
      if (isCurrent()) await exportDemandPredictionPdf({ data, locale, isCurrent });
    } catch {
      if (isCurrent()) setExportError(true);
    } finally {
      active.current = false;
      if (mounted.current) setExporting(false);
    }
  };
  return { exporting, exportError, clearExportError: () => setExportError(false), requestExport };
}

import { useState } from 'react';
import { Barcode } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ApexButton } from '../../../shared/components/apex/Apex.jsx';
import { cleanBarcode, isValidBarcode } from '../../../shared/utils/barcode.js';
import { useSetBarcode } from '../hooks/useCompetitorData.js';

// Enter or change a product's barcode. Checked while typing (same rule as the server),
// saved with the product, and the market-price lookup uses it as the exact key.
export function BarcodeEditor({ productId, value = null, compact = false }) {
  const { t } = useI18n();
  const [text, setText] = useState(value || '');
  const [saved, setSaved] = useState(false);
  const save = useSetBarcode();
  const typed = cleanBarcode(text);
  const invalid = typed.length > 0 && !isValidBarcode(typed);
  const unchanged = typed === (value || '');
  const serverRejected = save.isError && save.error?.response?.status === 422;

  const submit = (event) => {
    event.preventDefault();
    if (invalid || unchanged) return;
    setSaved(false);
    save.mutate({ productId, barcode: typed }, { onSuccess: () => setSaved(true) });
  };

  return (
    <form className={`barcode-editor${compact ? ' is-compact' : ''}`} onSubmit={submit}>
      <label>
        <span className={compact ? 'sr-only' : 'barcode-editor__label'}>{t('competitorData.barcode.label')}</span>
        <input
          type="text" inputMode="numeric" autoComplete="off" dir="ltr" value={text} placeholder={t('competitorData.barcode.placeholder')}
          aria-invalid={invalid || serverRejected || undefined}
          onChange={(event) => { setText(event.target.value); setSaved(false); }}
        />
      </label>
      <ApexButton type="submit" size="sm" variant="secondary" icon={Barcode} loading={save.isPending} disabled={invalid || unchanged}>
        {value ? t('competitorData.barcode.save') : t('competitorData.barcode.add')}
      </ApexButton>
      <span className="barcode-editor__note" role="status" aria-live="polite">
        {invalid || serverRejected ? t('competitorData.barcode.invalid') : saved ? t('competitorData.barcode.saved') : compact ? '' : t('competitorData.barcode.hint')}
      </span>
    </form>
  );
}

export default BarcodeEditor;

import { Calculator } from 'lucide-react';
import { CitationMarkers } from './CitationMarker.jsx';

const label = (t, key) => {
  const localeKey = `ragAssistant.calculation.inputs.${key}`;
  const text = t(localeKey);
  return text === localeKey ? key.replace(/_/g, ' ') : text;
};

// The headline figures of a KEEL calculation, taken from the calculation
// itself (never from the model's wording), with a reference marker that
// opens the full trace: every step, input, source, assumption and scenario.
export function CalculationCard({ calculation, onOpenRef, activeRef, t }) {
  if (!calculation) return null;
  const comparison = calculation.comparison;
  const step = (key) => (calculation.steps || []).find((item) => item.key === key);
  const perUnit = comparison?.landed_per_unit ?? step('landed_per_unit')?.value;
  const total = comparison?.landed_total ?? step('landed_total')?.value;
  const currency = comparison?.currency ?? step('landed_total')?.unit ?? '';
  const saving = comparison ? Number(comparison.saving_total) : null;
  return <section className="rag-calc-card" aria-label={t('ragAssistant.calculation.cardTitle')}>
    <header>
      <span><Calculator size={14} aria-hidden="true" />{t('ragAssistant.calculation.cardTitle')}</span>
      {Number.isInteger(calculation.ref) && <CitationMarkers refs={[calculation.ref]} onOpen={onOpenRef} activeRef={activeRef} t={t} />}
    </header>
    {perUnit != null && <dl>
      <div><dt>{t('ragAssistant.calculation.landedPerUnit')}</dt><dd><bdi>{perUnit} {currency}</bdi></dd></div>
      {total != null && <div><dt>{t('ragAssistant.calculation.landedTotal')}</dt><dd><bdi>{total} {currency}</bdi></dd></div>}
      {comparison && <div><dt>{t('ragAssistant.calculation.localPerUnit')}</dt><dd><bdi>{comparison.local_unit_price} {currency}</bdi></dd></div>}
      {comparison && <div><dt>{t(saving >= 0 ? 'ragAssistant.calculation.importSaves' : 'ragAssistant.calculation.importCostsMore')}</dt>
        <dd className={saving >= 0 ? 'is-saving' : 'is-cost'}><bdi>{Math.abs(saving).toFixed(3).replace(/\.?0+$/, '')} {currency}{comparison.saving_pct != null ? ` (${Math.abs(Number(comparison.saving_pct))}%)` : ''}</bdi></dd></div>}
      {comparison?.break_even_quantity && <div><dt>{t('ragAssistant.calculation.breakEven')}</dt><dd><bdi>{comparison.break_even_quantity}</bdi></dd></div>}
    </dl>}
    {calculation.missing?.length > 0 && <p>{t('ragAssistant.calculation.stillNeeded', { items: calculation.missing.map((item) => label(t, item.key)).join(t('ragAssistant.calculation.listSeparator')) })}</p>}
  </section>;
}

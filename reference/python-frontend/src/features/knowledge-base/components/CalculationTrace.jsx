import { CitationMarkers } from './CitationMarker.jsx';

const SOURCE_KEYS = { user: 'sourceUser', evidence: 'sourceEvidence', company: 'sourceCompany', assumption: 'sourceAssumption' };

// The localized name of a calculation input, or its key in plain words.
const inputLabel = (t, key) => {
  const localeKey = `ragAssistant.calculation.inputs.${key}`;
  const text = t(localeKey);
  return text === localeKey ? key.replace(/_/g, ' ') : text;
};

const withUnit = (value, unit) => (unit === 'percent' ? `${value}%` : unit && unit !== 'rate' && unit !== 'units' ? `${value} ${unit}` : value);

function InputList({ inputs, t }) {
  const entries = Object.entries(inputs || {});
  if (!entries.length) return null;
  return <dl className="rag-calc__inputs">{entries.map(([key, input]) => <div key={key}>
    <dt>{inputLabel(t, key)}</dt>
    <dd><bdi>{withUnit(input.value, input.unit)}</bdi>
      <small>{input.note || t(`ragAssistant.calculation.${SOURCE_KEYS[input.source] || 'sourceEvidence'}`)}</small></dd>
  </div>)}</dl>;
}

// How a KEEL calculation was derived: the formula of each step with its
// inputs and where each input came from, then assumptions, exclusions and
// anything still missing.
export function CalculationTrace({ calculation, inputRefs, onOpenRef, activeRef, t }) {
  if (!calculation) return null;
  const summary = calculation.summary;
  if (!summary) {
    return <div className="rag-calc">
      {calculation.formula && <p className="rag-calc__formula"><span>{t('ragAssistant.calculation.formula')}</span> <bdi>{calculation.formula}</bdi> = <bdi>{calculation.value}</bdi></p>}
      <InputList inputs={calculation.inputs} t={t} />
      {inputRefs?.length > 0 && <p className="rag-calc__sources">{t('ragAssistant.calculation.inputSources')} <CitationMarkers refs={inputRefs} onOpen={onOpenRef} activeRef={activeRef} t={t} /></p>}
    </div>;
  }
  return <div className="rag-calc">
    {summary.steps?.length > 0 && <div className="rag-answer-table-wrap"><table>
      <caption className="ceopro-visually-hidden">{t('ragAssistant.calculation.stepsCaption')}</caption>
      <thead><tr><th scope="col">{t('ragAssistant.calculation.step')}</th><th scope="col">{t('ragAssistant.calculation.formula')}</th><th scope="col">{t('ragAssistant.calculation.value')}</th></tr></thead>
      <tbody>{summary.steps.map((step) => <tr key={step.key}><th scope="row">{step.label}</th><td><bdi>{step.formula}</bdi></td><td><bdi>{withUnit(step.value, step.unit)}</bdi></td></tr>)}</tbody>
    </table></div>}
    <InputList inputs={summary.inputs} t={t} />
    {inputRefs?.length > 0 && <p className="rag-calc__sources">{t('ragAssistant.calculation.inputSources')} <CitationMarkers refs={inputRefs} onOpen={onOpenRef} activeRef={activeRef} t={t} /></p>}
    {summary.missing?.length > 0 && <div className="rag-calc__missing"><strong>{t('ragAssistant.calculation.missing')}</strong><ul>{summary.missing.map((item) => <li key={item.key}>{inputLabel(t, item.key)} — {item.why}</li>)}</ul></div>}
    {summary.assumptions?.length > 0 && <div><strong>{t('ragAssistant.calculation.assumptions')}</strong><ul>{summary.assumptions.map((text) => <li key={text}>{text}</li>)}</ul></div>}
    {summary.exclusions?.length > 0 && <div><strong>{t('ragAssistant.calculation.exclusions')}</strong><ul>{summary.exclusions.map((text) => <li key={text}>{text}</li>)}</ul></div>}
    {summary.sensitivity?.length > 0 && <div className="rag-answer-table-wrap"><table>
      <caption>{t('ragAssistant.calculation.sensitivity')}</caption>
      <thead><tr><th scope="col">{t('ragAssistant.calculation.scenario')}</th><th scope="col">{t('ragAssistant.calculation.perUnit')}</th><th scope="col">{t('ragAssistant.calculation.saving')}</th></tr></thead>
      <tbody>{summary.sensitivity.map((row) => <tr key={row.label}><th scope="row">{row.label}</th><td><bdi>{row.landed_per_unit}</bdi></td><td><bdi>{row.saving_total ?? '—'}</bdi></td></tr>)}</tbody>
    </table></div>}
  </div>;
}

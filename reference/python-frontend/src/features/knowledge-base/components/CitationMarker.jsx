// Small numbered reference markers placed right after a claim. Each number
// opens that reference in the answer's reference panel.
export function CitationMarkers({ refs, onOpen, activeRef, t }) {
  if (!refs?.length) return null;
  return <sup className="rag-cite">{refs.map((n, index) => <span key={n}>
    {index > 0 && <span className="rag-cite__sep" aria-hidden="true">,</span>}
    <button type="button" className={activeRef === n ? 'is-active' : undefined} onClick={(event) => onOpen(n, event.currentTarget)}
      aria-haspopup="dialog" aria-expanded={activeRef === n} aria-label={t('ragAssistant.references.open', { n })}>{n}</button>
  </span>)}</sup>;
}

import { useState } from 'react';
import { parseMarkdown } from '../utils/markdown.js';
import { CitationMarkers } from './CitationMarker.jsx';

const KIND_LABELS = {
  calculation: 'kindCalculation', estimate: 'kindEstimate', inference: 'kindInference',
  recommendation: 'kindRecommendation', assumption: 'kindAssumption', unknown: 'kindUnknown',
};

// One sentence of an answer: its text, a small label when it is not a plain
// fact (a calculation, an estimate, analysis, a recommendation, an
// assumption, or something that could not be established), a "not
// verified" mark when it could not be checked, then its reference markers.
function Claim({ claim, onOpenRef, activeRef, t }) {
  const label = KIND_LABELS[claim.kind];
  return <span className={`rag-claim is-${claim.kind}${claim.verified ? '' : ' is-unverified'}`}>
    {claim.text}
    {label && <span className="rag-claim__kind">{t(`ragAssistant.claims.${label}`)}</span>}
    {!claim.verified && <span className="rag-claim__unverified">{t('ragAssistant.claims.unverified')}</span>}
    {claim.notes.includes('unofficial_source') && <span className="rag-claim__unverified">{t('ragAssistant.claims.unofficial')}</span>}
    <CitationMarkers refs={claim.refs} onOpen={onOpenRef} activeRef={activeRef} t={t} />
  </span>;
}

function Claims({ claims, onOpenRef, activeRef, t }) {
  return claims.map((claim, index) => <span key={index}>{index > 0 && ' '}<Claim claim={claim} onOpenRef={onOpenRef} activeRef={activeRef} t={t} /></span>);
}

function CitedBlocks({ blocks, onOpenRef, activeRef, t }) {
  return <div className="rag-answer-copy">{blocks.map((block, index) => {
    if (block.type === 'heading') return <h4 key={index}>{block.text}</h4>;
    if (block.type === 'list') {
      const List = block.ordered ? 'ol' : 'ul';
      return <List key={index}>{block.items.map((item, k) => <li key={k}><Claims claims={item} onOpenRef={onOpenRef} activeRef={activeRef} t={t} /></li>)}</List>;
    }
    if (block.type === 'table') {
      return <div className="rag-answer-table-wrap" key={index}><table><thead><tr>{block.columns.map((column, c) => <th key={c} scope="col">{column}</th>)}</tr></thead>
        <tbody>{block.rows.map((row, r) => <tr key={r}>{block.columns.map((_, c) => <td key={c}><bdi>{row[c] ?? ''}</bdi></td>)}</tr>)}</tbody></table>
        {block.refs.length > 0 && <p className="rag-table-refs"><CitationMarkers refs={block.refs} onOpen={onOpenRef} activeRef={activeRef} t={t} /></p>}</div>;
    }
    return <p key={index}><Claims claims={block.claims} onOpenRef={onOpenRef} activeRef={activeRef} t={t} /></p>;
  })}</div>;
}

// A small, safe renderer for the Markdown the language model writes
// (tables, lists, headings, **bold**) - React elements only, never HTML.
function inline(text, keyBase) {
  return String(text).split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => (part.startsWith('**') && part.endsWith('**')
    ? <strong key={`${keyBase}-${index}`}>{part.slice(2, -2)}</strong>
    : <span key={`${keyBase}-${index}`}>{part}</span>));
}

function MarkdownAnswer({ text }) {
  return <div className="rag-answer-copy">{parseMarkdown(text).map((block, index) => {
    if (block.type === 'table') return <div className="rag-answer-table-wrap" key={index}><table><thead><tr>{block.head.map((cell, c) => <th key={c}>{inline(cell, `h${c}`)}</th>)}</tr></thead><tbody>{block.rows.map((row, r) => <tr key={r}>{block.head.map((_, c) => <td key={c}>{inline(row[c] ?? '', `c${r}-${c}`)}</td>)}</tr>)}</tbody></table></div>;
    if (block.type === 'list') { const List = block.ordered ? 'ol' : 'ul'; return <List key={index}>{block.items.map((item, k) => <li key={k}>{inline(item, `l${index}-${k}`)}</li>)}</List>; }
    if (block.type === 'heading') return <h4 key={index}>{inline(block.text, `t${index}`)}</h4>;
    return <p key={index}>{inline(block.text, `p${index}`)}</p>;
  })}</div>;
}

// An answer with claim-level references renders claim by claim; an older
// answer (saved before references existed) renders as the Markdown it was.
// A long answer opens on its short summary; the full answer is one click
// away (a native disclosure: keyboard and screen-reader friendly, no state).
function SummarisedAnswer({ summary, blocks, onOpenRef, activeRef, t }) {
  const [open, setOpen] = useState(false);
  return <>
    <p className="rag-answer-summary" dir="auto"><Claims claims={summary.claims} onOpenRef={onOpenRef} activeRef={activeRef} t={t} /></p>
    {summary.note && <p className="rag-answer-summary__note">{t(`ragAssistant.chat.summary_${summary.note}`)}</p>}
    <details className="rag-answer-details" open={open} onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{t(open ? 'ragAssistant.chat.hideFullAnswer' : 'ragAssistant.chat.showFullAnswer')}</summary>
      <CitedBlocks blocks={blocks} onOpenRef={onOpenRef} activeRef={activeRef} t={t} />
    </details>
  </>;
}

export function AssistantResponse({ content, blocks, summary, onOpenRef, activeRef, t }) {
  if (Array.isArray(blocks) && blocks.length && summary?.claims?.length) {
    return <SummarisedAnswer summary={summary} blocks={blocks} onOpenRef={onOpenRef} activeRef={activeRef} t={t} />;
  }
  if (Array.isArray(blocks) && blocks.length) return <CitedBlocks blocks={blocks} onOpenRef={onOpenRef} activeRef={activeRef} t={t} />;
  return <MarkdownAnswer text={typeof content === 'string' ? content : ''} />;
}

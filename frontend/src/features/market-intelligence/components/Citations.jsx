import { ExternalLink } from 'lucide-react';
import { safeHref } from '../../../shared/lib/safeUrl.js';

// The evidence an AI point rests on: numbered links to the page each fact
// came from (or the fact itself when it has no page, e.g. your own prices).
export function Citations({ citations, t }) {
  if (!citations?.length) return null;
  return (
    <span className="intel-citations">
      {citations.map((c) => (c.url ? (
        <a key={c.n} href={safeHref(c.url)} target="_blank" rel="noreferrer noopener" title={c.text} aria-label={t('intel.citation', { n: c.n, text: c.text })}>
          <sup>[{c.n}]</sup>
        </a>
      ) : <sup key={c.n} title={c.text} aria-label={t('intel.citation', { n: c.n, text: c.text })}>[{c.n}]</sup>))}
    </span>
  );
}

export function SourceLink({ url, t }) {
  if (!url) return null;
  let host = url;
  try { host = new URL(url).hostname.replace(/^www\./, ''); } catch { /* keep the raw link */ }
  return <a className="intel-source" href={safeHref(url)} target="_blank" rel="noreferrer noopener" dir="ltr" aria-label={t('intel.openSource', { host })}>{host}<ExternalLink size={10} aria-hidden="true" /></a>;
}

export function analysisErrorKey(error) {
  const status = error?.response?.status;
  if (!error?.response) return 'offline';
  if (status === 402) return 'planLimit';
  if (error.response.headers?.['x-assistant-reason'] === 'not_configured') return 'notConfigured';
  if (status === 503 || status === 429) return 'busy';
  return 'failed';
}

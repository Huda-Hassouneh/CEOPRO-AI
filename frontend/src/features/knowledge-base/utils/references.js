// Claim-level references for assistant answers (backend: rag/advisor.py and
// rag/citations.py). Pure functions only, so they are tested without a
// browser (tests/assistantReferences.test.mjs).

const SAFE_PROTOCOLS = new Set(['http:', 'https:']);

// An original-source link the panel may open: absolute http(s) only.
export function safeExternalUrl(url) {
  if (typeof url !== 'string' || !url) return null;
  try {
    const parsed = new URL(url);
    return SAFE_PROTOCOLS.has(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

// An in-app screen the panel may open: a path inside KEEL only.
export function safeInternalRoute(route) {
  if (typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//')) return null;
  return route;
}

function mapClaim(claim) {
  if (typeof claim === 'string') return { text: claim, kind: 'general', refs: [], verified: true, notes: [] };
  return {
    text: String(claim?.text ?? ''),
    kind: claim?.kind || 'general',
    refs: Array.isArray(claim?.refs) ? claim.refs.filter(Number.isInteger) : [],
    verified: claim?.verified !== false,
    notes: Array.isArray(claim?.notes) ? claim.notes : [],
  };
}

export function mapBlocks(blocks) {
  if (!Array.isArray(blocks)) return null;
  const mapped = blocks.map((block) => {
    if (block?.type === 'heading') return { type: 'heading', text: String(block.text ?? '') };
    if (block?.type === 'paragraph') return { type: 'paragraph', claims: (block.claims || []).map(mapClaim) };
    if (block?.type === 'list') {
      return { type: 'list', ordered: Boolean(block.ordered), items: (block.items || []).map((item) => (item || []).map(mapClaim)) };
    }
    if (block?.type === 'table') {
      return {
        type: 'table',
        columns: (block.columns || []).map(String),
        rows: (block.rows || []).map((row) => (row || []).map(String)),
        refs: Array.isArray(block.refs) ? block.refs.filter(Number.isInteger) : [],
      };
    }
    return null;
  }).filter(Boolean);
  return mapped.length ? mapped : null;
}

// The short answer shown above a long one: its claims, or null.
export function mapSummary(summary) {
  const claims = Array.isArray(summary?.claims) ? summary.claims.map(mapClaim) : [];
  return claims.length ? { claims, note: summary?.note === 'source_language' ? 'sourceLanguage' : null } : null;
}

export function mapReferences(references) {
  if (!Array.isArray(references)) return [];
  return references.filter((ref) => Number.isInteger(ref?.n)).map((ref) => ({
    n: ref.n,
    kind: ref.kind || 'company_record',
    title: ref.title || '',
    organisation: ref.organisation || null,
    url: safeExternalUrl(ref.url),
    route: safeInternalRoute(ref.route),
    locator: ref.locator || null,
    excerpt: ref.excerpt || '',
    publishedAt: ref.published_at || null,
    effectiveAt: ref.effective_at || null,
    observedAt: ref.observed_at || null,
    retrievedAt: ref.retrieved_at || null,
    jurisdiction: ref.jurisdiction || null,
    appliesTo: ref.applies_to || null,
    credibility: ref.credibility || null,
    status: ref.status || null,
    limitations: Array.isArray(ref.limitations) ? ref.limitations : [],
    usedAs: Array.isArray(ref.used_as) ? ref.used_as : [],
    inputRefs: Array.isArray(ref.input_refs) ? ref.input_refs.filter(Number.isInteger) : [],
    calculation: ref.calculation || null,
  }));
}

// The long-standing `sources` list, kept for answers saved before
// claim-level references existed.
export function mapLegacySources(sources) {
  if (!Array.isArray(sources)) return [];
  return sources.map((source, index) => (
    source?.url
      ? { citationId: `web-${index}`, name: source.title || source.url, uri: safeExternalUrl(source.url), sourceType: 'web' }
      : { citationId: source?.chunk_id || `source-${index}`, name: source?.title || `Source ${source?.source_index ?? index + 1}`, sourceType: 'knowledge-base' }
  ));
}

// An assistant answer (a /rag/query response or a stored message) in the
// shape the chat renders.
export function mapAnswer(data) {
  const references = mapReferences(data?.references);
  return {
    content: data?.answer ?? data?.content ?? '',
    summary: mapSummary(data?.answer_summary),
    blocks: mapBlocks(data?.answer_blocks),
    references,
    sources: references.length ? [] : mapLegacySources(data?.sources),
    calculations: Array.isArray(data?.calculations) ? data.calculations : [],
    followUpQuestions: Array.isArray(data?.follow_up_questions) ? data.follow_up_questions.map(String).slice(0, 3) : [],
    evidenceStatus: Array.isArray(data?.evidence_status) ? data.evidence_status : [],
    answerMode: data?.answer_mode || 'ai',
  };
}

export function referenceByNumber(references, n) {
  return (references || []).find((ref) => ref.n === n) || null;
}

// Status notes worth showing under an answer, as locale keys.
const STATUS_NOTES = {
  public_research: {
    not_configured: 'researchNotConfigured',
    budget_exhausted: 'researchBudget',
    search_failed: 'researchFailed',
    no_results: 'researchNoResults',
    pages_unreadable: 'researchUnreadable',
  },
  answer_writing: { not_configured: 'answerNotConfigured' },
  landed_cost_calculation: { missing_inputs: 'calculationMissing' },
  company_records: { none_found: 'companyRecordsNone' },
  customer_reviews: { none_recorded: 'reviewsNone', not_permitted: 'notPermitted' },
  company_documents: { not_permitted: 'notPermitted', failed: 'documentsFailed' },
};

export function statusNotes(evidenceStatus) {
  const keys = [];
  for (const entry of evidenceStatus || []) {
    const key = STATUS_NOTES[entry?.need]?.[entry?.status] || (entry?.status === 'not_permitted' ? 'notPermitted' : null);
    if (key && !keys.includes(key)) keys.push(key);
  }
  return keys;
}

// "1, 2" for an accessible label listing a claim's references.
export const referenceListLabel = (refs) => refs.join(', ');

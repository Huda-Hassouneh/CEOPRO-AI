// Turns a failed marketing request into the translation key (and values)
// the Studio shows. The server's own error text is English and partly meant
// for operators, so it is never shown as is.
//
// action: 'write' (campaign copy), 'image' (AI image), 'upload' (product
// photo), 'photo' (background removal / reference choice).

const PLAN_KEYS = {
  rag_assistant: 'planTokens',
  marketing_image_generation: 'planImages',
  document_storage_mb: 'planStorage',
  document_extraction: 'planUploads',
};

const FALLBACK_KEYS = { write: 'failed', image: 'imageFailed', upload: 'uploadFailed', photo: 'photoFailed' };

function renewalDate(periodEnd) {
  if (!periodEnd || !/^\d{4}-\d{2}-\d{2}$/.test(periodEnd)) return null;
  const next = new Date(`${periodEnd}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1); // the allowance renews the day after the period ends
  return next.toISOString().slice(0, 10);
}

export function describeMarketingError(error, { action = 'write', source } = {}) {
  const response = error?.response;
  if (!response) return { key: 'offline' };
  const status = response.status;

  if (status === 402) {
    const detail = typeof response.data?.detail === 'object' && response.data.detail ? response.data.detail : {};
    if (detail.reason === 'SUBSCRIPTION_INACTIVE') return { key: 'planInactive', billing: true };
    return {
      key: PLAN_KEYS[detail.feature_code] || 'planOther',
      billing: true,
      renewsOn: detail.reset_cycle === 'billing_period' ? renewalDate(detail.period_end) : null,
    };
  }
  if (status === 429 || status === 503) {
    if (action === 'write' && response.headers?.['x-assistant-reason'] === 'not_configured') return { key: 'notConfigured' };
    const seconds = Number.parseInt(response.headers?.['retry-after'], 10);
    return Number.isFinite(seconds) && seconds > 0 ? { key: 'busyFor', values: { seconds } } : { key: 'busy' };
  }
  if (action === 'upload' && status === 413) return { key: 'photoTooLarge' };
  if (action === 'upload' && status === 400) return { key: 'photoWrongType' };
  if (action === 'write' && status === 422 && source === 'link') return { key: 'badLink' };
  return { key: FALLBACK_KEYS[action] || 'failed' };
}

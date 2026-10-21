import { useCallback, useEffect, useState } from 'react';
import { ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { dataConnectionsApi } from '../api/dataConnectionsApi.js';

const ERROR_KEY = { 401: 'connectData.providerRecords.sessionExpired', 403: 'connectData.providerRecords.forbidden', 404: 'connectData.providerRecords.notFound', 409: 'connectData.providerRecords.conflict' };
const label = (t, key) => {
  const translated = t(key);
  return translated === key ? key.split('.').at(-1) : translated;
};

export function ProviderRecordsPanel({ source, refreshVersion, t }) {
  const [items, setItems] = useState([]);
  const [offset, setOffset] = useState(0);
  const [limit] = useState(25);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);
  const [history, setHistory] = useState({});
  const [historyBusy, setHistoryBusy] = useState(null);

  const load = useCallback(async (nextOffset = 0) => {
    setLoading(true);
    setError(null);
    try {
      const response = await dataConnectionsApi.providerRecords(source.source_id, { limit, offset: nextOffset });
      setItems(response.items || []);
      setOffset(nextOffset);
    } catch (requestError) {
      setError(label(t, ERROR_KEY[requestError?.response?.status] || 'connectData.providerRecords.loadFailed'));
    } finally {
      setLoading(false);
    }
  }, [limit, source.source_id, t]);

  useEffect(() => { load(0); }, [load, refreshVersion]);

  const toggleHistory = async (identityId) => {
    if (history[identityId]) {
      setHistory((current) => ({ ...current, [identityId]: null }));
      return;
    }
    setHistoryBusy(identityId);
    try {
      const response = await dataConnectionsApi.providerRecordHistory(source.source_id, identityId);
      setHistory((current) => ({ ...current, [identityId]: response.revisions || [] }));
    } catch (requestError) {
      setError(label(t, ERROR_KEY[requestError?.response?.status] || 'connectData.providerRecords.loadFailed'));
    } finally {
      setHistoryBusy(null);
    }
  };

  const decide = async (item, decision) => {
    const message = label(t, decision === 'approve' ? 'connectData.providerRecords.confirmApprove' : 'connectData.providerRecords.confirmReject');
    if (!globalThis.confirm(message)) return;
    setPending(item.business_revision_id);
    setError(null);
    try {
      await dataConnectionsApi.reviewProviderRecord(source.source_id, {
        business_revision_id: item.business_revision_id,
        decision,
        idempotency_key: globalThis.crypto.randomUUID(),
        reason_code: decision === 'approve' ? 'tenant_review_approved' : 'tenant_review_rejected',
      });
      await load(offset);
      setHistory((current) => ({ ...current, [item.provider_record_identity_id]: null }));
    } catch (requestError) {
      setError(label(t, ERROR_KEY[requestError?.response?.status] || 'connectData.providerRecords.reviewFailed'));
    } finally {
      setPending(null);
    }
  };

  return <section className="connect-data-section provider-records" aria-labelledby={`provider-records-${source.source_id}`}>
    <div className="connect-data-section__header">
      <div><h2 id={`provider-records-${source.source_id}`}>{t('connectData.providerRecords.title')}: {source.name}</h2>
        <p>{t('connectData.providerRecords.notice')}</p></div>
      <Button size="sm" variant="outline" leadingIcon={<RefreshCw size={14} />} onClick={() => load(offset)} disabled={loading}>{t('connectData.providerRecords.refresh')}</Button>
    </div>
    {error && <p className="provider-records__error" role="alert">{error}</p>}
    {loading ? <p aria-live="polite">{t('connectData.providerRecords.loading')}</p> : items.length === 0
      ? <p className="provider-records__empty">{t('connectData.providerRecords.empty')}</p>
      : <div className="connect-data-table-wrap" tabIndex={0} role="region" aria-label={t('connectData.providerRecords.tableLabel')}>
        <table className="connect-data-table provider-records__table"><thead><tr>
          <th>{t('connectData.providerRecords.type')}</th><th>{t('connectData.providerRecords.providerId')}</th>
          <th>{t('connectData.providerRecords.values')}</th><th>{t('connectData.providerRecords.validation')}</th>
          <th>{t('connectData.providerRecords.review')}</th><th>{t('connectData.providerRecords.actions')}</th>
        </tr></thead><tbody>{items.map((item) => <tr key={item.business_revision_id}>
          <td>{t(`connectData.providerRecords.entities.${item.entity_type}`)}</td>
          <td><code>{item.provider_record_id}</code></td>
          <td><dl className="provider-records__values">{Object.entries(item.typed_values || {}).slice(0, 8).map(([key, value]) => <div key={key}>
            <dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd>
          </div>)}</dl></td>
          <td><strong>{t(`connectData.providerRecords.states.${item.validation_status}`)}</strong>
            {!!item.validation_findings?.length && <ul>{item.validation_findings.map((finding, index) => <li key={`${finding.code}-${index}`}>{finding.field}: {finding.code}</li>)}</ul>}
          </td>
          <td>{item.review_decision ? t(`connectData.providerRecords.decisions.${item.review_decision}`) : t('connectData.providerRecords.states.notReviewed')}</td>
          <td><div className="provider-records__actions">
            <Button size="sm" variant="outline" leadingIcon={history[item.provider_record_identity_id] ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              disabled={historyBusy === item.provider_record_identity_id} onClick={() => toggleHistory(item.provider_record_identity_id)}>
              {t('connectData.providerRecords.history')}
            </Button>
            {!item.review_decision && <>
              <Button size="sm" variant="outline" disabled={pending === item.business_revision_id || item.validation_status === 'invalid'} onClick={() => decide(item, 'approve')}>{t('connectData.providerRecords.approve')}</Button>
              <Button size="sm" variant="ghost" disabled={pending === item.business_revision_id} onClick={() => decide(item, 'reject')}>{t('connectData.providerRecords.reject')}</Button>
            </>}
          </div></td>
        </tr>)}</tbody></table>
      </div>}
    {historyBusy && <p aria-live="polite">{t('connectData.providerRecords.loadingHistory')}</p>}
    {items.map((item) => history[item.provider_record_identity_id]?.length > 0 && <ol className="provider-records__history" key={`history-${item.provider_record_identity_id}`}>
      {history[item.provider_record_identity_id].map((revision) => <li key={revision.business_revision_id}>
        {t('connectData.providerRecords.revision', { number: revision.revision_number })} · {t(`connectData.providerRecords.states.${revision.validation_status}`)}
        {revision.review && ` · ${t(`connectData.providerRecords.decisions.${revision.review.decision}`)} · ${revision.review.reason_code}`}
        <dl className="provider-records__values">{Object.entries(revision.typed_values || {}).slice(0, 8).map(([key, value]) => <div key={key}>
          <dt>{key}</dt><dd>{typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—')}</dd>
        </div>)}</dl>
        {!!revision.validation_findings?.length && <ul>{revision.validation_findings.map((finding, index) => <li key={`${finding.code}-${index}`}>{finding.field}: {finding.code}</li>)}</ul>}
      </li>)}
    </ol>)}
    <div className="provider-records__pagination">
      <Button size="sm" variant="outline" disabled={loading || offset === 0} onClick={() => load(Math.max(0, offset - limit))}>{t('connectData.providerRecords.previous')}</Button>
      <span>{t('connectData.providerRecords.page', { page: Math.floor(offset / limit) + 1 })}</span>
      <Button size="sm" variant="outline" disabled={loading || items.length < limit} onClick={() => load(offset + limit)}>{t('connectData.providerRecords.next')}</Button>
    </div>
    <p className="provider-records__boundary">{t('connectData.providerRecords.notPosted')}</p>
  </section>;
}

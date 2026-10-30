import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, Check, ChevronLeft, ChevronRight, Eye, FileClock, RefreshCw, X } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { hasAnyRole } from '../../auth/permissions/rolePermissions.js';
import { importDraftsApi, describeImportApiError, importDraftStateKey } from '../api/importDraftsApi.js';

const PAGE_SIZE = 10;
const ROWS_PER_PAGE = 25;
const CATEGORIES = ['sales', 'invoice', 'inventory'];

function errorMessage(error, t) {
  return describeImportApiError(error, t);
}

function StatePill({ state, t }) {
  const key = importDraftStateKey(state);
  const label = t(key);
  return <span className={`import-draft-state is-${String(state || 'draft').toLowerCase()}`}>{label === key ? state : label}</span>;
}

function FieldValues({ values, locale, t }) {
  if (!values || Object.keys(values).length === 0) return <span className="import-draft-muted">—</span>;
  const entries = Object.entries(values);
  return <dl className="import-draft-fields">
    {entries.map(([field, value]) => {
      const fieldLabel = t(`connectData.drafts.fields.${field}`);
      const isReference = ['product_id', 'provider_product_id', 'location_id', 'provider_location_id'].includes(field);
      const printable = isReference && value
        ? t('connectData.drafts.references.present')
        : ['transaction_date', 'invoice_date', 'observed_at'].includes(field) && value
        ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(value))
        : typeof value === 'object' ? JSON.stringify(value) : String(value);
      return <div key={field}><dt>{fieldLabel === `connectData.drafts.fields.${field}` ? field.replaceAll('_', ' ') : fieldLabel}</dt><dd><bdi>{printable}</bdi></dd></div>;
    })}
  </dl>;
}

function Findings({ findings, t }) {
  if (!Array.isArray(findings) || findings.length === 0) return <span className="import-draft-muted">—</span>;
  return <ul className="import-draft-findings">
    {findings.map((finding, index) => {
      const codeKey = `connectData.drafts.findings.${finding.code}`;
      const translatedCode = t(codeKey);
      const fieldKey = `connectData.drafts.fields.${finding.field}`;
      const translatedField = t(fieldKey);
      const field = translatedField === fieldKey ? String(finding.field || '').replaceAll('_', ' ') : translatedField;
      const code = translatedCode === codeKey ? String(finding.code || '').replaceAll('_', ' ') : translatedCode;
      return <li key={`${finding.field}-${finding.code}-${index}`}><strong>{field}:</strong> {code}</li>;
    })}
  </ul>;
}

function ReviewLabel({ decision, t }) {
  if (!decision) return <span className="import-draft-muted">{t('connectData.drafts.review.pending')}</span>;
  const reviewKey = decision.decision === 'approve' ? 'approved' : 'rejected';
  return <span className={`import-draft-review is-${decision.decision}`}>
    {decision.decision === 'approve' ? <Check size={14} aria-hidden="true" /> : <X size={14} aria-hidden="true" />}
    {t(`connectData.drafts.review.${reviewKey}`)}
  </span>;
}

export function ImportDraftsPanel({ t, locale }) {
  const queryClient = useQueryClient();
  const roles = useAuthStore((state) => state.roles);
  const canReview = hasAnyRole(roles, ['owner', 'admin']);
  const [page, setPage] = useState(0);
  const [category, setCategory] = useState('');
  const [selectedBatch, setSelectedBatch] = useState(null);
  const [selectedRevision, setSelectedRevision] = useState(null);
  const [rowPage, setRowPage] = useState(0);
  const [confirmation, setConfirmation] = useState(null);
  const [reason, setReason] = useState('');
  const [reviewError, setReviewError] = useState('');
  const retryKey = useRef(null);
  const number = useMemo(() => new Intl.NumberFormat(locale), [locale]);
  const date = useMemo(() => new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }), [locale]);

  const listQuery = useQuery({
    queryKey: ['import-drafts', page, category],
    queryFn: () => importDraftsApi.list({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, category: category || undefined }),
  });
  const detailQuery = useQuery({
    queryKey: ['import-draft', selectedBatch, selectedRevision],
    queryFn: () => importDraftsApi.detail(selectedBatch, selectedRevision),
    enabled: Boolean(selectedBatch),
  });
  const revisionsQuery = useQuery({
    queryKey: ['import-draft-revisions', selectedBatch],
    queryFn: () => importDraftsApi.revisions(selectedBatch),
    enabled: Boolean(selectedBatch),
  });
  const historyQuery = useQuery({
    queryKey: ['import-draft-reviews', selectedBatch, selectedRevision],
    queryFn: () => importDraftsApi.reviews(selectedBatch, selectedRevision || undefined),
    enabled: Boolean(selectedBatch),
  });
  const decisionMutation = useMutation({
    mutationFn: ({ batchId, payload }) => importDraftsApi.decide(batchId, payload),
    onSuccess: async () => {
      setReviewError('');
      setConfirmation(null);
      setReason('');
      retryKey.current = null;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['import-drafts'] }),
        queryClient.invalidateQueries({ queryKey: ['import-draft', selectedBatch] }),
        queryClient.invalidateQueries({ queryKey: ['import-draft-reviews', selectedBatch] }),
      ]);
    },
    onError: (error) => {
      setReviewError(errorMessage(error, t));
      if (error?.response?.status === 409) {
        setConfirmation(null);
        retryKey.current = null;
        queryClient.invalidateQueries({ queryKey: ['import-drafts'] });
        queryClient.invalidateQueries({ queryKey: ['import-draft', selectedBatch] });
      }
    },
  });

  const items = listQuery.data?.items || [];
  const detail = detailQuery.data;
  const revisions = revisionsQuery.data?.revisions || [];
  const reviews = historyQuery.data?.reviews || [];
  const rows = detail?.rows || [];
  const rowCount = rows.length;
  const visibleRows = rows.slice(rowPage * ROWS_PER_PAGE, (rowPage + 1) * ROWS_PER_PAGE);
  const isCurrent = detail?.is_current_revision !== false;
  const terminal = ['approved', 'rejected'].includes(String(detail?.state || '').toLowerCase());
  const batchCanApprove = rows.every((row) => row.validation_outcome === 'valid' || row.review_decision?.decision === 'approve');
  const selectedRevisionNumber = revisions.find((item) => item.revision_id === (selectedRevision || detail?.current_revision_id))?.revision_number;

  const openDraft = (item) => {
    setSelectedBatch(item.batch_id);
    setSelectedRevision(null);
    setRowPage(0);
    setReviewError('');
  };
  const closeDetail = () => {
    setSelectedBatch(null);
    setSelectedRevision(null);
    setRowPage(0);
    setReviewError('');
  };
  const requestDecision = (decision, rowId = null) => {
    setReason('');
    setReviewError('');
    retryKey.current = null;
    setConfirmation({ decision, rowId });
  };
  const submitDecision = async (event) => {
    event.preventDefault();
    if (!confirmation || !detail || decisionMutation.isPending) return;
    if (!retryKey.current) retryKey.current = globalThis.crypto?.randomUUID?.() || `review-${Date.now()}-${Math.random().toString(36).slice(2)}`;
    await decisionMutation.mutateAsync({
      batchId: selectedBatch,
      payload: {
        revision_id: detail.revision_id,
        decision: confirmation.decision,
        idempotency_key: retryKey.current,
        reason_code: reason.trim(),
        ...(confirmation.rowId ? { row_id: confirmation.rowId } : {}),
      },
    }).catch(() => {});
  };
  const formatDate = (value) => value ? date.format(new Date(value)) : t('connectData.drafts.notAvailable');
  const categoryLabel = (value) => t(`connectData.drafts.categories.${value}`);
  const errorForStatus = (error) => errorMessage(error, t);

  return <section className="connect-data-section import-drafts" aria-labelledby="import-drafts-title">
    <div className="connect-data-section__header">
      <div><h2 id="import-drafts-title">{t('connectData.drafts.title')}</h2><p>{t('connectData.drafts.subtitle')}</p></div>
      <Button size="sm" variant="outline" leadingIcon={<RefreshCw size={14} />} onClick={() => listQuery.refetch()} loading={listQuery.isFetching}>
        {t('connectData.drafts.refresh')}
      </Button>
    </div>
    <p className="import-drafts-notice" role="note">{t('connectData.drafts.reviewIsNotPosting')}</p>
    <div className="import-drafts-toolbar">
      <label htmlFor="import-draft-category">{t('connectData.drafts.filterLabel')}</label>
      <select id="import-draft-category" value={category} onChange={(event) => { setCategory(event.target.value); setPage(0); }}>
        <option value="">{t('connectData.drafts.allCategories')}</option>
        {CATEGORIES.map((value) => <option key={value} value={value}>{categoryLabel(value)}</option>)}
      </select>
    </div>

    {listQuery.isPending ? <div aria-busy="true" className="import-drafts-skeleton"><Skeleton height="46px" /><Skeleton height="190px" /></div>
      : listQuery.isError ? <div className="import-drafts-error" role="alert"><AlertCircle size={18} />{errorForStatus(listQuery.error)} <Button size="sm" variant="outline" onClick={() => listQuery.refetch()}>{t('connectData.drafts.retry')}</Button></div>
        : items.length === 0 ? <EmptyState title={t('connectData.drafts.emptyTitle')} description={t('connectData.drafts.emptyDescription')} />
          : <>
            <div className="connect-data-table-wrap import-drafts-table-wrap" role="region" aria-label={t('connectData.drafts.listLabel')} tabIndex={0}>
              <table className="connect-data-table import-drafts-list-table">
                <thead><tr><th scope="col">{t('connectData.drafts.date')}</th><th scope="col">{t('connectData.drafts.source')}</th><th scope="col">{t('connectData.drafts.category')}</th><th scope="col">{t('connectData.drafts.validation')}</th><th scope="col">{t('connectData.drafts.reviewLabel')}</th><th scope="col">{t('connectData.drafts.posting')}</th><th scope="col">{t('connectData.drafts.actions')}</th></tr></thead>
                <tbody>{items.map((item) => <tr key={item.batch_id}>
                  <td>{formatDate(item.created_at)}</td>
                  <td>{item.source_name || t('connectData.drafts.unknownSource')}</td>
                  <td>{categoryLabel(item.category)}</td>
                  <td>{number.format(item.invalid_row_count || 0)} {t('connectData.drafts.invalidCount')} · {number.format(item.review_required_row_count || 0)} {t('connectData.drafts.ambiguousCount')}</td>
                  <td><StatePill state={item.review_status || item.state} t={t} /></td>
                  <td><StatePill state={item.posting_status} t={t} /></td>
                  <td><Button size="sm" variant="outline" leadingIcon={<Eye size={14} />} onClick={() => openDraft(item)}>{t('connectData.drafts.open')}</Button></td>
                </tr>)}</tbody>
              </table>
            </div>
            <div className="import-drafts-pagination" aria-label={t('connectData.drafts.paginationLabel')}>
              <span>{t('connectData.drafts.page', { page: number.format(page + 1) })}</span>
              <Button size="sm" variant="ghost" leadingIcon={<ChevronLeft size={15} />} disabled={page === 0 || listQuery.isFetching} onClick={() => setPage((current) => Math.max(0, current - 1))}>{t('connectData.drafts.previous')}</Button>
              <Button size="sm" variant="ghost" trailingIcon={<ChevronRight size={15} />} disabled={items.length < PAGE_SIZE || listQuery.isFetching} onClick={() => setPage((current) => current + 1)}>{t('connectData.drafts.next')}</Button>
            </div>
          </>}

    {selectedBatch && <section className="import-draft-detail" aria-labelledby="import-draft-detail-title">
      <div className="import-draft-detail__heading">
        <div><h3 id="import-draft-detail-title">{t('connectData.drafts.previewTitle')}</h3><p>{t('connectData.drafts.previewSubtitle')}</p></div>
        <Button size="sm" variant="ghost" leadingIcon={<X size={15} />} onClick={closeDetail}>{t('connectData.drafts.closePreview')}</Button>
      </div>
      {detailQuery.isPending ? <div aria-busy="true"><Skeleton height="60px" /><Skeleton height="260px" /></div>
        : detailQuery.isError ? <div className="import-drafts-error" role="alert"><AlertCircle size={18} />{errorForStatus(detailQuery.error)} <Button size="sm" variant="outline" onClick={() => detailQuery.refetch()}>{t('connectData.drafts.retry')}</Button></div>
          : detail && <>
            <div className="import-draft-summary">
              <div><span>{t('connectData.drafts.category')}</span><strong>{categoryLabel(detail.category)}</strong></div>
              <div><span>{t('connectData.drafts.source')}</span><strong>{detail.source_name || t('connectData.drafts.unknownSource')}</strong></div>
              <div><span>{t('connectData.drafts.ingestion')}</span><strong>{detail.ingestion_status || t('connectData.drafts.notAvailable')}</strong></div>
              <div><span>{t('connectData.drafts.revision')}</span><strong>{number.format(selectedRevisionNumber || detail.revision_number || 1)}{!isCurrent ? ` · ${t('connectData.drafts.superseded')}` : ''}</strong></div>
              <div><span>{t('connectData.drafts.reviewLabel')}</span><StatePill state={detail.review_status || detail.state} t={t} /></div>
              <div><span>{t('connectData.drafts.posting')}</span><StatePill state={detail.posting_status} t={t} /></div>
            </div>
            <div className="import-draft-warning" role="note"><strong>{t('connectData.drafts.reviewIsNotPostingTitle')}</strong><span>{detail.category === 'invoice' ? t('connectData.drafts.invoiceBoundary') : detail.category === 'inventory' ? t('connectData.drafts.inventoryBoundary') : t('connectData.drafts.salesBoundary')}</span></div>

            <div className="import-draft-controls">
              <label htmlFor="import-draft-revision">{t('connectData.drafts.revisionHistory')}</label>
              {revisionsQuery.isError ? <span role="alert">{errorForStatus(revisionsQuery.error)}</span> : <select id="import-draft-revision" value={selectedRevision || detail.current_revision_id || detail.revision_id} onChange={(event) => { setSelectedRevision(event.target.value); setRowPage(0); }}>
                {revisions.map((revision) => <option key={revision.revision_id} value={revision.revision_id}>{t('connectData.drafts.revisionOption', { number: revision.revision_number, date: formatDate(revision.created_at) })}{revision.revision_id !== detail.current_revision_id ? ` · ${t('connectData.drafts.superseded')}` : ''}</option>)}
              </select>}
              {!isCurrent && <span className="import-draft-stale">{t('connectData.drafts.staleRevision')}</span>}
            </div>

            <div className="connect-data-table-wrap import-draft-rows-wrap" role="region" aria-label={t('connectData.drafts.rowsLabel')} tabIndex={0}>
              <table className="connect-data-table import-draft-rows-table">
                <thead><tr><th scope="col">{t('connectData.drafts.row')}</th><th scope="col">{t('connectData.drafts.record')}</th><th scope="col">{t('connectData.drafts.validationFindings')}</th><th scope="col">{t('connectData.drafts.reviewLabel')}</th><th scope="col">{t('connectData.drafts.posting')}</th><th scope="col">{t('connectData.drafts.actions')}</th></tr></thead>
                <tbody>{visibleRows.map((row) => <tr key={row.draft_row_id}>
                  <td>{number.format(row.row_number)}</td>
                  <td><FieldValues values={row.typed_values} locale={locale} t={t} /></td>
                  <td><Findings findings={row.validation_findings} t={t} />{row.ambiguity_code && <span className="import-draft-stale">{t('connectData.drafts.needsAssociationReview')}</span>}</td>
                  <td><ReviewLabel decision={row.review_decision} t={t} /></td>
                  <td><StatePill state={row.canonical_posting_status} t={t} /></td>
                  <td>{canReview && isCurrent && !terminal && row.validation_outcome !== 'valid'
                    ? <div className="import-draft-row-actions"><Button size="sm" variant="outline" disabled={decisionMutation.isPending} onClick={() => requestDecision('approve', row.draft_row_id)}>{t('connectData.drafts.approveRow')}</Button><Button size="sm" variant="ghost" disabled={decisionMutation.isPending} onClick={() => requestDecision('reject', row.draft_row_id)}>{t('connectData.drafts.rejectRow')}</Button></div>
                    : <span className="import-draft-muted">—</span>}</td>
                </tr>)}</tbody>
              </table>
              {rowCount === 0 && <p className="import-draft-muted import-draft-no-rows">{t('connectData.drafts.noRows')}</p>}
            </div>
            {rowCount > ROWS_PER_PAGE && <div className="import-drafts-pagination"><span>{t('connectData.drafts.rowsPage', { from: number.format(rowPage * ROWS_PER_PAGE + 1), to: number.format(Math.min((rowPage + 1) * ROWS_PER_PAGE, rowCount)), count: number.format(rowCount) })}</span><Button size="sm" variant="ghost" disabled={rowPage === 0} onClick={() => setRowPage((current) => Math.max(0, current - 1))}>{t('connectData.drafts.previous')}</Button><Button size="sm" variant="ghost" disabled={(rowPage + 1) * ROWS_PER_PAGE >= rowCount} onClick={() => setRowPage((current) => current + 1)}>{t('connectData.drafts.next')}</Button></div>}

            {canReview && isCurrent && !terminal && <div className="import-draft-batch-actions">
              {rowCount > 0 && batchCanApprove && <Button size="sm" leadingIcon={<Check size={15} />} onClick={() => requestDecision('approve')}>{t('connectData.drafts.approveBatch')}</Button>}
              <Button size="sm" variant="outline" leadingIcon={<X size={15} />} onClick={() => requestDecision('reject')}>{t('connectData.drafts.rejectBatch')}</Button>
            </div>}
            {reviewError && <div className="import-drafts-error" role="alert"><AlertCircle size={17} />{reviewError}{decisionMutation.error?.response?.status === 409 && <Button size="sm" variant="outline" onClick={() => { setSelectedRevision(null); detailQuery.refetch(); historyQuery.refetch(); }}>{t('connectData.drafts.reloadCurrent')}</Button>}</div>}

            <section className="import-draft-history" aria-labelledby="import-draft-history-title">
              <h4 id="import-draft-history-title"><FileClock size={16} aria-hidden="true" />{t('connectData.drafts.reviewHistory')}</h4>
              {historyQuery.isPending ? <Skeleton height="48px" /> : historyQuery.isError ? <div className="import-drafts-error" role="alert">{errorForStatus(historyQuery.error)}</div>
                : reviews.length ? <ol>{reviews.map((review) => { const reviewKey = review.decision === 'approve' ? 'approved' : 'rejected'; return <li key={review.decision_id}><span className={`import-draft-review is-${review.decision}`}>{t(`connectData.drafts.review.${reviewKey}`)}</span><time dateTime={review.created_at}>{formatDate(review.created_at)}</time><span>{review.reason_code}</span></li>; })}</ol>
                  : <p className="import-draft-muted">{t('connectData.drafts.noReviewHistory')}</p>}
            </section>
          </>}
    </section>}

    <Modal isOpen={Boolean(confirmation)} onClose={() => { if (!decisionMutation.isPending) { setConfirmation(null); setReviewError(''); retryKey.current = null; } }} title={confirmation ? t(`connectData.drafts.confirm.${confirmation.decision}.title`) : ''} closeLabel={t('common.close')} maxWidth="520px" footer={<><Button variant="ghost" disabled={decisionMutation.isPending} onClick={() => setConfirmation(null)}>{t('connectData.drafts.cancel')}</Button><Button loading={decisionMutation.isPending} loadingLabel={t('connectData.drafts.submitting')} disabled={!reason.trim()} onClick={submitDecision}>{t('connectData.drafts.confirmAction')}</Button></>}>
      {confirmation && <form className="import-draft-confirm" onSubmit={submitDecision}>
        <p>{t(`connectData.drafts.confirm.${confirmation.decision}.body`)}</p>
        <p className="import-draft-warning"><strong>{t('connectData.drafts.reviewIsNotPostingTitle')}</strong><span>{t('connectData.drafts.confirm.notPosting')}</span></p>
        <label htmlFor="import-review-reason">{t('connectData.drafts.reasonLabel')}</label>
        <textarea id="import-review-reason" rows="3" maxLength="100" required value={reason} onChange={(event) => setReason(event.target.value)} />
        {reviewError && <p className="import-drafts-error" role="alert">{reviewError}</p>}
      </form>}
    </Modal>
  </section>;
}

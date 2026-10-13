import { useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { PendingSourcesTable } from '../components/PendingSourcesTable.jsx';
import { ReviewSourceModal } from '../components/ReviewSourceModal.jsx';
import { usePendingSources } from '../hooks/usePendingSources.js';
import { useReviewSource } from '../hooks/useReviewSource.js';
import '../styles/MarketIntelligence.css';

const STATUS_FILTERS = ['RESTRICTED', 'ALLOWED', 'BLOCKED'];

// The real review queue - discovery correctly finds and classifies
// competitors, but every automated discovery result lands here
// RESTRICTED (occasionally BLOCKED) until a real owner/admin reviews the
// source's own Terms of Service - see source_review.py's own docstring
// for why that's an intentional gate, never a bug to route around.
export function PendingSourcesPage() {
  const { t, dir } = useI18n();
  const navigate = useNavigate();
  const [status, setStatus] = useState('RESTRICTED');
  const [reviewing, setReviewing] = useState(null);
  const [toast, setToast] = useState(null);
  const sourcesQuery = usePendingSources(status);
  const reviewSource = useReviewSource();

  const submitReview = async ({ termsPermit, reviewerReference }) => {
    try {
      const result = await reviewSource.mutateAsync({ sourceId: reviewing.source_id, termsPermit, reviewerReference });
      setReviewing(null);
      setToast({
        variant: result.status === 'ALLOWED' ? 'success' : 'info',
        message: t(`market.sources.review.result.${result.status}`),
      });
    } catch {
      setToast({ variant: 'error', message: t('market.sources.review.error') });
    }
  };

  const counts = sourcesQuery.data?.counts;
  const rows = sourcesQuery.data?.sources ?? [];

  return <DashboardLayout>
    <div className="market-page pending-sources-page" dir={dir}>
      <button type="button" className="market-back-link" onClick={() => navigate('/market')}>
        <ArrowLeft size={15} />{t('market.sources.back')}
      </button>
      <PageHeader title={t('market.sources.title')} subtitle={t('market.sources.subtitle')} />

      {toast && <Toast variant={toast.variant} message={toast.message} onClose={() => setToast(null)} />}

      <div className="pending-sources-page__filters" role="tablist" aria-label={t('market.sources.filterLabel')}>
        {STATUS_FILTERS.map((option) => <button
          key={option}
          type="button"
          role="tab"
          aria-selected={status === option}
          className={`pending-sources-page__filter${status === option ? ' is-active' : ''}`}
          onClick={() => setStatus(option)}
        >
          {t(`market.sources.status.${option}`)}
          {counts && <Badge variant="neutral">{counts[option] ?? 0}</Badge>}
        </button>)}
      </div>

      {sourcesQuery.isPending
        ? <Skeleton height="320px" variant="rectangular" />
        : sourcesQuery.isError
          ? <EmptyState title={t('market.sources.errorTitle')} description={t('market.sources.errorDescription')} />
          : rows.length === 0
            ? <EmptyState title={t('market.sources.emptyTitle')} description={t(`market.sources.emptyDescription.${status}`)} />
            : <PendingSourcesTable t={t} rows={rows} onReview={setReviewing} />}

      <ReviewSourceModal
        t={t}
        source={reviewing}
        isPending={reviewSource.isPending}
        onSubmit={submitReview}
        onClose={() => setReviewing(null)}
      />
    </div>
  </DashboardLayout>;
}

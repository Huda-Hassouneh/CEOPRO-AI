import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';

// The real approve/reject decision policy.py::evaluate_source() has
// always required before a discovered source becomes a collection
// target - see source_review.py's own docstring. reviewer_reference must
// be a real, non-empty note (what the backend persists as
// approval_reference on approval, or in technical_restrictions either
// way) - never left blank and auto-filled.
export function ReviewSourceModal({ t, source, isPending, onSubmit, onClose }) {
  const [termsPermit, setTermsPermit] = useState('yes');
  const [reference, setReference] = useState('');
  const trimmedReference = reference.trim();

  const submit = (event) => {
    event.preventDefault();
    if (!trimmedReference || isPending) return;
    onSubmit({ termsPermit: termsPermit === 'yes', reviewerReference: trimmedReference });
  };

  return <Modal
    isOpen={Boolean(source)}
    onClose={onClose}
    title={t('market.sources.review.title')}
    closeLabel={t('common.close')}
    maxWidth="560px"
    footer={<>
      <Button variant="outline" onClick={onClose} disabled={isPending}>{t('market.sources.review.cancel')}</Button>
      <Button onClick={submit} disabled={!trimmedReference} loading={isPending} loadingLabel={t('market.sources.review.submitting')}>
        {t('market.sources.review.submit')}
      </Button>
    </>}
  >
    {source && <form className="review-source-form" onSubmit={submit}>
      <p className="review-source-form__source"><strong>{source.competitor_name || source.source_name}</strong><small>{source.source_url}</small></p>
      <p className="review-source-form__subtitle">{t('market.sources.review.subtitle')}</p>

      <fieldset className="review-source-form__terms">
        <legend>{t('market.sources.review.termsQuestion')}</legend>
        <label className={`review-source-option${termsPermit === 'yes' ? ' is-selected' : ''}`}>
          <input type="radio" name="terms-permit" value="yes" checked={termsPermit === 'yes'} onChange={() => setTermsPermit('yes')} />
          <span>{t('market.sources.review.termsYes')}</span>
        </label>
        <label className={`review-source-option${termsPermit === 'no' ? ' is-selected' : ''}`}>
          <input type="radio" name="terms-permit" value="no" checked={termsPermit === 'no'} onChange={() => setTermsPermit('no')} />
          <span>{t('market.sources.review.termsNo')}</span>
        </label>
      </fieldset>

      <label className="review-source-form__reference-label" htmlFor="review-source-reference">{t('market.sources.review.referenceLabel')}</label>
      <textarea
        id="review-source-reference"
        className="review-source-form__reference"
        rows={3}
        placeholder={t('market.sources.review.referencePlaceholder')}
        value={reference}
        onChange={(event) => setReference(event.target.value)}
      />
      <p className="review-source-form__help">{t('market.sources.review.referenceHelp')}</p>
    </form>}
  </Modal>;
}

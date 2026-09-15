import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { getPreviewPlan } from '../config/billingPreviewData.js';

export function StandardPlanRecommendation({ open, onClose, onTryPro, onContinueStandard }) {
  const { t } = useI18n();
  const trialDays = getPreviewPlan('pro').trialDays;

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={t('billing.recommendation.title')}
      maxWidth="430px"
      className="ceopro-standard-recommendation"
      footer={(
        <>
          <Button variant="outline" onClick={onContinueStandard}>{t('billing.recommendation.continueStandard')}</Button>
          <Button onClick={onTryPro}>{t('billing.recommendation.tryPro', { days: trialDays })}</Button>
        </>
      )}
    >
      <p>{t('billing.recommendation.description', { days: trialDays })}</p>
    </Modal>
  );
}

import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function StandardPlanRecommendation({
  open,
  onClose,
  onTryRecommended,
  onContinueCurrent,
  currentPlanName,
  recommendedPlanName,
  trialDays = 0,
}) {
  const { t } = useI18n();

  if (!trialDays || !currentPlanName || !recommendedPlanName) return null;

  const values = {
    days: trialDays,
    currentPlan: currentPlanName,
    recommendedPlan: recommendedPlanName,
  };

  return (
    <Modal
      isOpen={open}
      onClose={onClose}
      title={t('billing.recommendation.title', values)}
      maxWidth="430px"
      className="ceopro-standard-recommendation"
      footer={(
        <>
          <Button variant="outline" onClick={onContinueCurrent}>
            {t('billing.recommendation.continueCurrent', values)}
          </Button>
          <Button onClick={onTryRecommended}>
            {t('billing.recommendation.tryRecommended', values)}
          </Button>
        </>
      )}
    >
      <p>{t('billing.recommendation.description', values)}</p>
    </Modal>
  );
}

import { ArrowLeft, ArrowRight } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function OnboardingActions({ onBack, onContinue, continueLabel, disabled = false, loading = false }) {
  const { t } = useI18n();

  return (
    <div className={`ceopro-setup-actions ${onBack ? '' : 'ceopro-setup-actions--end'}`.trim()}>
      {onBack && (
        <Button variant="outline" onClick={onBack} leadingIcon={<ArrowLeft className="ceopro-setup-direction-icon" size={16} />}>
          {t('onboarding.common.back')}
        </Button>
      )}
      <Button
        onClick={onContinue}
        disabled={disabled}
        loading={loading}
        trailingIcon={<ArrowRight className="ceopro-setup-direction-icon" size={16} />}
      >
        {continueLabel || t('onboarding.common.continue')}
      </Button>
    </div>
  );
}

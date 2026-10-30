import { useEffect, useRef } from 'react';
import Stepper from '../../../shared/components/ui/Stepper.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { ONBOARDING_STEP_COUNT } from '../config/onboardingSteps.js';

export function OnboardingPageShell({ step, title, subtitle, children, wide = false, showProgress = true }) {
  const { t } = useI18n();
  const headingRef = useRef(null);
  const steps = Array.from({ length: ONBOARDING_STEP_COUNT }, (_, index) => ({
    id: index + 1,
    label: t('onboarding.common.stepAccessible', { step: index + 1 }),
  }));

  useEffect(() => {
    headingRef.current?.focus({ preventScroll: true });
  }, [title]);

  return (
    <section className={`ceopro-setup-page ${wide ? 'ceopro-setup-page--wide' : ''}`.trim()}>
      {showProgress && (
        <div className="ceopro-setup-progress">
          <strong>{t('onboarding.common.stepOf', { step, total: ONBOARDING_STEP_COUNT })}</strong>
          <Stepper
            steps={steps}
            currentStep={step}
            showLabels={false}
            ariaLabel={t('onboarding.common.progressLabel')}
          />
        </div>
      )}
      {(title || subtitle) && (
        <header className="ceopro-setup-page__heading">
          {title && <h1 ref={headingRef} tabIndex="-1">{title}</h1>}
          {subtitle && <p>{subtitle}</p>}
        </header>
      )}
      {children}
    </section>
  );
}

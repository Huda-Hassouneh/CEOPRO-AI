import React from 'react';

export default function Stepper({
  steps = [],
  currentStep = 1,
  className = '',
  ariaLabel = 'Progress',
  showLabels = true,
  ...props
}) {
  return (
    <ol
      className={`ceopro-stepper ${showLabels ? '' : 'ceopro-stepper--compact'} ${className}`.trim()}
      aria-label={ariaLabel}
      {...props}
    >
      {steps.map((step, index) => {
        const item = typeof step === 'string' ? { id: step, label: step } : step;
        const stepNumber = index + 1;
        const isCompleted = stepNumber < currentStep;
        const isCurrent = stepNumber === currentStep;

        return (
          <li
            key={item.id || item.label || stepNumber}
            className={`ceopro-stepper__item ${isCompleted ? 'is-completed' : ''} ${isCurrent ? 'is-current' : ''}`.trim()}
            aria-current={isCurrent ? 'step' : undefined}
          >
            <span className="ceopro-stepper__marker" aria-hidden="true">
              {isCompleted ? '✓' : stepNumber}
            </span>
            {showLabels && <span className="ceopro-stepper__label">{item.label}</span>}
            <span className="ceopro-visually-hidden">{item.accessibleLabel || item.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

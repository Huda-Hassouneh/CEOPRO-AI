import { CheckCircle2, XCircle } from 'lucide-react';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { getPasswordRequirementState } from '../validation/authValidation.js';

export function PasswordRequirements({ password, visible = true }) {
  const { t } = useI18n();
  if (!visible) return null;
  const requirements = getPasswordRequirementState(password);

  return (
    <div className="ceopro-password-requirements" aria-live="polite">
      <p className="ceopro-password-requirements__title">{t('auth.passwordRequirements.title')}</p>
      <ul className="ceopro-password-requirements__list">
        {requirements.map((requirement) => (
          <li
            className={`ceopro-password-requirements__item ${requirement.met ? 'is-met' : 'is-unmet'}`}
            key={requirement.id}
          >
            {requirement.met
              ? <CheckCircle2 size={16} aria-hidden="true" />
              : <XCircle size={16} aria-hidden="true" />}
            <span className="ceopro-visually-hidden">
              {t(requirement.met ? 'auth.passwordRequirements.met' : 'auth.passwordRequirements.unmet')}:{' '}
            </span>
            <span>{t(requirement.labelKey, requirement.params)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

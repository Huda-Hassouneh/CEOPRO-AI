import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import React from 'react';

export default function PasswordStrength({ score = 0, title, label, hint }) {
  const { t: copyT } = useI18n();
  title ??= copyT("interfaceCopy.passwordStrength");
  label ??= copyT("interfaceCopy.weak");
  hint ??= copyT("interfaceCopy.use8CharactersWithAMixOfLettersNumbersAndSymbols");
  const levels = [
    { key: 'weak', label: copyT("interfaceCopy.weak") },
    { key: 'fair', label: copyT("interfaceCopy.fair") },
    { key: 'good', label: copyT("interfaceCopy.good") },
    { key: 'strong', label: copyT("interfaceCopy.strong") },
  ];

  return (
    <div className="ceopro-password-strength" aria-live="polite">
      <div className="ceopro-password-strength__meta">
        <span>{title}</span>
        <strong>{label}</strong>
      </div>

      <div className="ceopro-password-strength__bars" aria-hidden="true">
        {levels.map((item, index) => {
          const isActive = index < score;
          const className = [
            'ceopro-password-strength__bar',
            isActive ? (score >= 4 ? 'is-success' : score >= 3 ? 'is-warning' : 'is-danger') : '',
          ].filter(Boolean).join(' ');

          return <span key={item.key} className={className} />;
        })}
      </div>

      <div className="ceopro-password-strength__hint">{hint}</div>
    </div>
  );
}

import React from 'react';

export default function PasswordStrength({ score = 0, title = 'Password strength', label = 'Weak', hint = 'Use 8+ characters with a mix of letters, numbers, and symbols.' }) {
  const levels = [
    { key: 'weak', label: 'Weak' },
    { key: 'fair', label: 'Fair' },
    { key: 'good', label: 'Good' },
    { key: 'strong', label: 'Strong' },
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

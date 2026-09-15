import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

export function AuthPanel({ title, subtitle, children, className = '' }) {
  return (
    <div className={`ceopro-auth-body ${className}`.trim()}>
      {(title || subtitle) && (
        <header className="ceopro-auth-header">
          {title && <h1 className="ceopro-auth-title">{title}</h1>}
          {subtitle && <p className="ceopro-auth-subtitle">{subtitle}</p>}
        </header>
      )}
      {children}
    </div>
  );
}

export function AuthBackLink({ to = routePaths.login, children }) {
  const { t } = useI18n();

  return (
    <div className="ceopro-auth-back-link">
      <Link className="ceopro-auth-link" to={to}>
        <ArrowLeft className="ceopro-auth-direction-icon" size={19} strokeWidth={2.5} aria-hidden="true" />
        <span>{children || t('auth.common.backToLogin')}</span>
      </Link>
    </div>
  );
}

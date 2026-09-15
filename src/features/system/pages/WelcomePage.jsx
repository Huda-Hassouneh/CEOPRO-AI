import React from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { AuthLanguageSwitch } from '../../auth/components/AuthLanguageSwitch.jsx';
import './WelcomePage.css';

export default function WelcomePage() {
  const navigate = useNavigate();
  const { dir, t } = useI18n();

  return (
    <div className="ceopro-welcome-page" dir={dir}>
      <div className="ceopro-welcome-page__shape ceopro-welcome-page__shape--top" aria-hidden="true" />
      <div className="ceopro-welcome-page__shape ceopro-welcome-page__shape--bottom" aria-hidden="true" />
      <AuthLanguageSwitch />

      <div className="ceopro-welcome-page__content">
        <div className="ceopro-welcome-page__brand" aria-label={t('common.brand')}>{t('common.brand')}</div>

        <section className="ceopro-welcome-card" aria-labelledby="welcome-heading">
          <img
            className="ceopro-welcome-card__illustration"
            src="/assets/images/welcomeimage.png"
            alt={t('auth.welcome.imageAlt')}
          />

          <div className="ceopro-welcome-card__copy">
            <h1 id="welcome-heading">{t('auth.welcome.title')}</h1>
            <p className="ceopro-welcome-card__tagline">{t('auth.welcome.tagline')}</p>
            <p className="ceopro-welcome-card__description">
              {t('auth.welcome.descriptionLine1')}<br />
              {t('auth.welcome.descriptionLine2')}
            </p>
          </div>

          <div className="ceopro-welcome-card__actions">
            <Button variant="primary" fullWidth onClick={() => navigate(routePaths.login)}>{t('auth.welcome.login')}</Button>
            <Button variant="outline" fullWidth onClick={() => navigate(routePaths.signup)}>{t('auth.welcome.signup')}</Button>
          </div>

          <div className="ceopro-welcome-card__divider" aria-label={t('auth.welcome.newTo')}>
            <span>{t('auth.welcome.newTo')}</span>
          </div>
        </section>
      </div>
    </div>
  );
}

import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { useI18n } from '../providers/I18nProvider.jsx';
import { AccountPopover } from '../../features/onboarding/components/AccountPopover.jsx';
import '../../features/onboarding/styles/Onboarding.css';
import '../../features/billing/styles/Billing.css';
import '../../features/data-connections/styles/DataConnections.css';
import '../../features/data-ingestion/styles/DataIngestion.css';

export function OnboardingLayout({ children }) {
  const { pathname } = useLocation();
  const { t, dir } = useI18n();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <div className="ceopro-setup" dir={dir}>
      <header className="ceopro-setup-header">
        <div className="ceopro-setup-header__identity">
          <span className="ceopro-setup-header__brand">{t('common.brandShort')}</span>
          <span className="ceopro-setup-header__divider" aria-hidden="true" />
          <span className="ceopro-setup-header__label">{t('onboarding.common.setup')}</span>
        </div>

        <div className="ceopro-setup-header__controls">
          <AccountPopover />
        </div>
      </header>
      <main className="ceopro-setup-main">{children}</main>
    </div>
  );
}

import { ArrowLeft, Building2, ScanBarcode } from 'lucide-react';
import { Link } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';

const placeholderIcons = { pos: ScanBarcode, erp: Building2 };

export function OnboardingBusinessSystemPlaceholderPage({ system }) {
  const { t } = useI18n();
  const Icon = placeholderIcons[system];

  return (
    <OnboardingPageShell wide showProgress={false}>
      <div className="ceopro-database-panel">
        <Link className="ceopro-subpage-back" to={routePaths.onboardingConnectDataBusinessSystem}><ArrowLeft className="ceopro-setup-direction-icon" size={14} />{t('dataConnections.businessSystem.backToSelection')}</Link>
        <div className="ceopro-data-source-card ceopro-business-system-placeholder">
          <span className="ceopro-data-source-card__icon" aria-hidden="true"><Icon size={28} /></span>
          <h1>{t(`dataConnections.businessSystem.options.${system}.title`)}</h1>
          <p>{t('dataConnections.businessSystem.placeholder')}</p>
        </div>
      </div>
    </OnboardingPageShell>
  );
}

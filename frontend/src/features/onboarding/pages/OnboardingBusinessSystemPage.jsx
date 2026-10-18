import { ArrowLeft, Building2, Database, ScanBarcode } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DataSourceCard } from '../../data-connections/components/DataSourceCard.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';

const BUSINESS_SYSTEM_OPTIONS = [
  { id: 'database', icon: Database, route: 'onboardingConnectDataDatabase' },
  { id: 'pos', icon: ScanBarcode, route: 'onboardingConnectDataPos' },
  { id: 'erp', icon: Building2, route: 'onboardingConnectDataErp' },
];

export function OnboardingBusinessSystemPage() {
  const navigate = useNavigate();
  const { t } = useI18n();

  return (
    <OnboardingPageShell wide showProgress={false}>
      <div className="ceopro-database-panel">
        <Link className="ceopro-subpage-back" to={routePaths.onboardingConnectData}><ArrowLeft className="ceopro-setup-direction-icon" size={14} />{t('dataConnections.businessSystem.back')}</Link>
        <header className="ceopro-setup-page__heading">
          <span className="ceopro-data-source-card__icon"><Building2 size={28} /></span>
          <h1>{t('dataConnections.businessSystem.pageTitle')}</h1>
          <p>{t('dataConnections.businessSystem.pageSubtitle')}</p>
        </header>
        <div className="ceopro-database-grid ceopro-business-system-grid">
          {BUSINESS_SYSTEM_OPTIONS.map(({ id, icon: Icon, route }) => (
            <DataSourceCard
              key={id}
              icon={<Icon size={27} />}
              title={t(`dataConnections.businessSystem.options.${id}.title`)}
              description={t(`dataConnections.businessSystem.options.${id}.description`)}
              actionLabel={t('dataConnections.businessSystem.select')}
              showStatus={false}
              onAction={() => navigate(routePaths[route])}
            />
          ))}
        </div>
      </div>
    </OnboardingPageShell>
  );
}

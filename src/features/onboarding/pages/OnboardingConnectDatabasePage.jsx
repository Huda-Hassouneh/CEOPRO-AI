import { ArrowLeft, Database, ShieldCheck } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DatabaseProviderCard } from '../../data-connections/components/DatabaseProviderCard.jsx';
import { DATABASE_PROVIDER_ASSETS } from '../../data-connections/config/providerAssets.js';
import { connectionProviders } from '../../data-connections/types/dataConnections.types.js';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingConnectDatabasePage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const databaseProvider = useOnboardingStore((state) => state.databaseProvider);
  const setDatabaseProvider = useOnboardingStore((state) => state.setDatabaseProvider);

  return (
    <OnboardingPageShell wide showProgress={false}>
      <div className="ceopro-database-panel">
        <Link className="ceopro-subpage-back" to={routePaths.onboardingConnectDataBusinessSystem}><ArrowLeft className="ceopro-setup-direction-icon" size={14} />{t('dataConnections.businessSystem.backToSelection')}</Link>
        <header className="ceopro-setup-page__heading">
          <span className="ceopro-data-source-card__icon"><Database size={28} /></span>
          <h1>{t('dataConnections.database.pageTitle')}</h1>
          <p>{t('dataConnections.database.pageSubtitle')}</p>
        </header>
        <h2>{t('dataConnections.database.chooseType')}</h2>
        <div className="ceopro-database-grid">
          {connectionProviders.map((provider) => (
            <DatabaseProviderCard
              key={provider}
              provider={provider}
              title={t(`dataConnections.database.providers.${provider}.title`)}
              description={t(`dataConnections.database.providers.${provider}.description`)}
              icon={DATABASE_PROVIDER_ASSETS[provider]}
              selected={databaseProvider === provider}
              onSelect={setDatabaseProvider}
            />
          ))}
        </div>
        <div className="ceopro-security-note"><ShieldCheck size={21} aria-hidden="true" /><span><strong>{t('dataConnections.database.securityTitle')}</strong><br />{t('dataConnections.database.securityDescription')}</span></div>
        <div className="ceopro-setup-actions">
          <Button variant="outline" onClick={() => navigate(routePaths.onboardingConnectDataBusinessSystem)}>{t('onboarding.common.back')}</Button>
          <div className="ceopro-database-actions">
            <Button variant="secondary" disabled title={t('dataConnections.database.testUnavailable')}>{t('dataConnections.database.test')}</Button>
            <Button disabled={!databaseProvider} onClick={() => navigate(routePaths.onboardingConnectData)}>{t('onboarding.common.continue')}</Button>
          </div>
        </div>
      </div>
    </OnboardingPageShell>
  );
}

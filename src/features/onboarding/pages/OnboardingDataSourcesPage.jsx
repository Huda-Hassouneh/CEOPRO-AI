import { Building2, FileText, Link2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../../shared/components/ui/Button.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { dataConnectionsApi } from '../../data-connections/api/dataConnectionsApi.js';
import { DataSourceCard } from '../../data-connections/components/DataSourceCard.jsx';
import { DATA_SOURCE_ASSETS } from '../../data-connections/config/providerAssets.js';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';
import { useOnboardingStore } from '../store/onboardingStore.js';

export function OnboardingDataSourcesPage() {
  const navigate = useNavigate();
  const { t } = useI18n();
  const sourceStatuses = useOnboardingStore((state) => state.sourceStatuses);
  const websiteUrl = useOnboardingStore((state) => state.websiteUrl);
  const setSourceStatus = useOnboardingStore((state) => state.setSourceStatus);
  const setWebsiteUrl = useOnboardingStore((state) => state.setWebsiteUrl);
  const completeSetup = useOnboardingStore((state) => state.completeSetup);
  const getSource = (source) => sourceStatuses[source] || { status: 'not-connected', error: '' };
  const connectedCount = Object.values(sourceStatuses).filter((source) => source.status === 'connected').length;

  const completeAndExit = () => {
    completeSetup();
    navigate(routePaths.dashboard);
  };

  const connectAnalytics = async () => {
    setSourceStatus('analytics', 'connecting');
    const result = await dataConnectionsApi.connectGoogleAnalytics();
    if (result.connected) setSourceStatus('analytics', 'connected');
    else setSourceStatus('analytics', 'error', t('dataConnections.analytics.oauthUnavailable'));
  };

  const connectWebsite = async () => {
    setSourceStatus('website', 'connecting');
    const result = await dataConnectionsApi.configureWebsite({ url: websiteUrl.trim() });
    setSourceStatus('website', result.connected ? 'connected' : 'error', result.connected ? '' : t('dataConnections.website.error'));
  };

  const analytics = getSource('analytics');
  const website = getSource('website');
  const businessSystem = getSource('database');
  const documents = getSource('documents');

  return (
    <OnboardingPageShell wide step={6} title={t('dataConnections.title')} subtitle={t('dataConnections.subtitle')}>
      <div className="ceopro-data-source-grid">
        <DataSourceCard
          iconSrc={DATA_SOURCE_ASSETS.googleAnalytics}
          title={t('dataConnections.analytics.title')}
          description={t('dataConnections.analytics.description')}
          actionLabel={t('dataConnections.analytics.action')}
          status={analytics.status}
          error={analytics.error}
          loading={analytics.status === 'connecting'}
          onAction={connectAnalytics}
        />
        <DataSourceCard
          icon={<Link2 size={27} />}
          title={t('dataConnections.website.title')}
          description={t('dataConnections.website.description')}
          actionLabel={t('dataConnections.website.action')}
          status={website.status}
          error={website.error}
          loading={website.status === 'connecting'}
          actionDisabled={!websiteUrl.trim()}
          onAction={connectWebsite}
        >
          <input
            className="ceopro-setup-url-input"
            type="url"
            value={websiteUrl}
            placeholder="https://your-website.com"
            aria-label={t('dataConnections.website.inputLabel')}
            onChange={(event) => {
              setWebsiteUrl(event.target.value);
              if (website.status !== 'not-connected') setSourceStatus('website', 'not-connected');
            }}
          />
        </DataSourceCard>
        <DataSourceCard
          icon={<Building2 size={27} />}
          title={t('dataConnections.businessSystem.title')}
          description={t('dataConnections.businessSystem.description')}
          actionLabel={t('dataConnections.businessSystem.action')}
          status={businessSystem.status}
          error={businessSystem.error}
          onAction={() => navigate(routePaths.onboardingConnectDataBusinessSystem)}
        />
        <DataSourceCard
          icon={<FileText size={27} />}
          title={t('dataConnections.documents.title')}
          description={t('dataConnections.documents.description')}
          actionLabel={t('dataConnections.documents.action')}
          status={documents.status}
          error={documents.error}
          onAction={() => navigate(routePaths.onboardingConnectDataUpload)}
        />
      </div>
      {connectedCount > 0 && <p className="ceopro-connection-summary" role="status">{t('dataConnections.connectedCount', { count: connectedCount })}</p>}
      <div className="ceopro-setup-actions">
        <Button variant="outline" onClick={() => navigate(routePaths.onboardingPlan)}>{t('onboarding.common.back')}</Button>
        <div className="ceopro-connect-data-actions">
          <Button variant="ghost" onClick={completeAndExit}>{t('dataConnections.skip')}</Button>
          <Button disabled={connectedCount === 0} onClick={completeAndExit}>{t('dataConnections.completeSetup')}</Button>
        </div>
      </div>
    </OnboardingPageShell>
  );
}

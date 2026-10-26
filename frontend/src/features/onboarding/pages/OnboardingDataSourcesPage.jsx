import { Building2, FileText, Link2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { companyApi } from '../../settings/api/companyApi.js';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { ConnectStoreForm } from '../../data-connections/components/ConnectStoreForm.jsx';
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
  const queryClient=useQueryClient();
  const sourceStatuses = useOnboardingStore((state) => state.sourceStatuses);
  const websiteUrl = useOnboardingStore((state) => state.websiteUrl);
  const setSourceStatus = useOnboardingStore((state) => state.setSourceStatus);
  const setWebsiteUrl = useOnboardingStore((state) => state.setWebsiteUrl);
  const [finishing,setFinishing]=useState(false),[finishError,setFinishError]=useState('');
  const sources=useQuery({queryKey:['onboarding-connected-sources'],queryFn:dataConnectionsApi.list});
  useEffect(()=>{for(const source of sources.data?.connectedSources||[]){
    const group=source.collector_key?.includes('woocommerce')||source.collector_key?.includes('shopify')?'website':source.collector_key?.includes('database')?'database':null;
    if(group)setSourceStatus(group,source.is_active===false?'not-connected':'connected');
  }},[sources.data,setSourceStatus]);
  const getSource = (source) => sourceStatuses[source] || { status: 'not-connected', error: '' };
  const [storeSetupOpen,setStoreSetupOpen]=useState(false);
  const connectedCount = Object.values(sourceStatuses).filter((source) => ['connected', 'configured'].includes(source.status)).length;

  const completeAndExit = async () => {
    setFinishing(true);setFinishError('');
    try{await companyApi.completeOnboarding();await queryClient.invalidateQueries({queryKey:['settings-company']});await queryClient.invalidateQueries({queryKey:['onboarding-state']});navigate(routePaths.dashboard,{replace:true});}
    catch(error){setFinishError(error?.response?.data?.detail||t('onboarding.persistence.error'));}
    finally{setFinishing(false);}
  };

  const connectAnalytics = async () => {
    setSourceStatus('analytics', 'connecting');
    setSourceStatus('analytics', 'error', t('dataConnections.analytics.oauthUnavailable'));
  };

  const connectWebsite = () => setStoreSetupOpen(true);

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
          actionLabel={t(['configured', 'connected'].includes(website.status) ? 'dataConnections.website.added' : 'dataConnections.website.action')}
          status={website.status}
          error={website.error}
          loading={website.status === 'connecting'}
          actionDisabled={!websiteUrl.trim() || ['connecting', 'configured', 'connected'].includes(website.status)}
          onAction={connectWebsite}
        >
          <input
            className="ceopro-setup-url-input"
            type="url"
            disabled={website.status === 'connecting'}
            value={websiteUrl}
            placeholder={t("dataConnections.website.placeholder")}
            aria-label={t('dataConnections.website.inputLabel')}
            onChange={(event) => {
              setWebsiteUrl(event.target.value);
              if (website.status !== 'not-connected') setSourceStatus('website', 'not-connected');
            }}
          />
          {website.status === 'configured' && <p role="status">{t('dataConnections.website.configuredNotice')}</p>}
        </DataSourceCard>
        <DataSourceCard
          icon={<Building2 size={27} />}
          title={t('dataConnections.businessSystem.title')}
          description={t('dataConnections.businessSystem.description')}
          actionLabel={t('dataConnections.businessSystem.action')}
          status={businessSystem.status}
          error={businessSystem.error}
          onAction={() => navigate(routePaths.connectData)}
        />
        <DataSourceCard
          icon={<FileText size={27} />}
          title={t('dataConnections.documents.title')}
          description={t('dataConnections.documents.description')}
          actionLabel={t('dataConnections.documents.action')}
          status={documents.status}
          error={documents.error}
          onAction={() => navigate(routePaths.connectData)}
        />
      </div>
      {connectedCount > 0 && <p className="ceopro-connection-summary" role="status">{t('dataConnections.addedCount', { count: connectedCount })}</p>}
      <Modal isOpen={storeSetupOpen} onClose={()=>setStoreSetupOpen(false)} title={t('dataConnections.website.title')}>
        <ConnectStoreForm provider="woocommerce" t={t} onCancel={()=>setStoreSetupOpen(false)} onDone={()=>{setSourceStatus('website','connected');sources.refetch();setStoreSetupOpen(false);}}/>
      </Modal>
      {finishError&&<p role="alert">{finishError}</p>}
      <div className="ceopro-setup-actions">
        <Button variant="outline" onClick={() => navigate(routePaths.onboardingPlan)}>{t('onboarding.common.back')}</Button>
        <div className="ceopro-connect-data-actions">
          <Button variant="ghost" loading={finishing} onClick={completeAndExit}>{t('dataConnections.skip')}</Button>
          <Button disabled={connectedCount === 0} loading={finishing} onClick={completeAndExit}>{t('dataConnections.completeSetup')}</Button>
        </div>
      </div>
    </OnboardingPageShell>
  );
}

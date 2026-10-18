import {COMPETITOR_AI_ACTIONS_ENABLED} from '../config/competitorCapabilities.js';
import {Navigate} from 'react-router-dom';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { getApiErrorMessage } from '../../../shared/lib/apiErrors.js';
import { AddCompetitorForm } from '../components/AddCompetitorForm.jsx';
import { useAddCompetitor } from '../hooks/useAddCompetitor.js';
import { FeatureGate } from '../../billing/components/FeatureGate.jsx';
import '../styles/MarketIntelligence.css';
function ConnectedAddCompetitorPage() {
  const { t }=useI18n(); const navigate=useNavigate(); const mutation=useAddCompetitor();
  const submit=async values=>{ try { await mutation.mutateAsync(values); navigate('/market/competitors'); } catch { /* Keep the form and entered values visible. */ } };
  return <DashboardLayout><div className="add-competitor-page"><button type="button" className="market-back-link" onClick={()=>navigate('/market/competitors')}>{t('market.detail.back')}</button>
    <section className="add-competitor-card"><h1>{t('market.modal.title')}</h1><FeatureGate featureCode="competitor_management" compact>
      <AddCompetitorForm t={t} onSubmit={submit} onCancel={()=>navigate('/market/competitors')} busy={mutation.isPending} error={mutation.error && getApiErrorMessage(mutation.error,t)} />
    </FeatureGate></section></div></DashboardLayout>;
}

export function AddCompetitorPage() { return COMPETITOR_AI_ACTIONS_ENABLED ? <ConnectedAddCompetitorPage/> : <Navigate to="/market/competitors" replace/>; }

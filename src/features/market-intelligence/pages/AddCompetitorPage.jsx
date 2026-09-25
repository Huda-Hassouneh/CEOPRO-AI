import { ArrowLeft } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { AddCompetitorForm } from '../components/AddCompetitorForm.jsx';
import { addPreviewCompetitor } from '../config/competitorPreviewData.js';
import { FeatureGate } from '../../billing/components/FeatureGate.jsx';
import '../styles/MarketIntelligence.css';

export function AddCompetitorPage() {
  const { t } = useI18n(); const navigate = useNavigate();
  return <DashboardLayout><div className="add-competitor-page"><button type="button" className="market-back-link" onClick={() => navigate('/market/competitors')}><ArrowLeft size={15} />{t('market.detail.back')}</button><section className="add-competitor-card"><div className="add-competitor-card__brand">CEO PRO</div><h1>{t('market.modal.title')}</h1><FeatureGate featureCode="tracked_competitors" mode="consume" compact><AddCompetitorForm t={t} onSubmit={(values) => { addPreviewCompetitor(values); navigate('/market/competitors'); }} onCancel={() => navigate('/market/competitors')} /></FeatureGate></section></div></DashboardLayout>;
}

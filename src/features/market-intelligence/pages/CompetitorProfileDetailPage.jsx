import { ExternalLink } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import Card from '../../../shared/components/ui/Card.jsx';
import { MarketMetricCard } from '../components/MarketMetricCard.jsx';
import { MarketTrendChart } from '../components/MarketTrendChart.jsx';
import { CompetitorDetailHeader, CompetitorSummary, StrengthsWeaknesses, StrategicMoves, PriceComparison } from '../components/CompetitorDetailSections.jsx';
import { competitorDetailsById } from '../config/competitorPreviewData.js';
import '../styles/MarketIntelligence.css';

export function CompetitorProfileDetailPage() {
  const { t } = useI18n(); const navigate = useNavigate(); const { competitorId = 'orange' } = useParams(); const detail = competitorDetailsById[competitorId] || competitorDetailsById.orange;
  return <DashboardLayout><div className="market-page competitor-detail-page">
    <CompetitorDetailHeader t={t} detail={detail} onBack={() => navigate('/market/competitors')} />
    <section className="market-metric-grid competitor-detail-metrics">{detail.metrics.map((item,index)=><MarketMetricCard key={item.labelKey} item={{...item,value:item.value||t(item.valueKey),trendKey:'market.common.vsLastMonth',progress:index<3?Number.parseFloat(item.sub)||undefined:undefined}} t={t}/>)}</section>
    <section className="market-grid market-grid--trend"><Card className="market-panel market-trend-panel"><div className="market-panel__header"><div><h2>{t('market.detail.presenceTitle')}</h2><p>{t('market.detail.presenceSubtitle')}</p></div><select className="market-filter-select"><option>{t('market.controls.last12')}</option></select></div><MarketTrendChart current={detail.presence.current} previous={detail.presence.previous} labels={['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']} ariaLabel={t('market.detail.presenceChartLabel')}/></Card><CompetitorSummary t={t} detail={detail}/></section>
    <StrengthsWeaknesses t={t} detail={detail}/><StrategicMoves t={t} moves={detail.moves}/>
    <section className="market-panel competitor-products"><div className="market-panel__header"><div><h2>{t('market.detail.productsTitle')}</h2><p>{t('market.detail.productsSubtitle')}</p></div><div className="detail-table-controls"><select><option>{t('market.detail.allCategories')}</option></select><input placeholder={t('market.detail.searchProducts')}/></div></div><div className="market-table-wrap"><table className="market-table"><thead><tr><th>{t('market.detail.productName')}</th><th>{t('market.detail.category')}</th><th>{t('market.detail.type')}</th><th>{t('market.detail.currentPrice')}</th><th>{t('market.detail.lastUpdated')}</th><th>{t('market.competitors.actions')}</th></tr></thead><tbody>{detail.products.map((item)=><tr key={item.id}><td><strong>{item.name}</strong></td><td>{t(item.categoryKey)}</td><td>{t(item.typeKey)}</td><td>{item.price} / {t('marketProductData.perMonth')}</td><td>{t(item.updatedKey)}</td><td><button className="market-table-action" type="button" onClick={()=>navigate('/market/competitors/'+competitorId+'/products/'+item.id)}>{t('market.competitors.viewDetails')}</button></td></tr>)}</tbody></table></div></section>
    <section className="market-grid market-grid--two"><PriceComparison t={t} data={detail.priceComparison}/><Card className="market-panel"><div className="market-panel__header"><h2>{t('market.detail.recentActivity')}</h2><button className="market-link">{t('market.controls.viewAll')} <ExternalLink size={13}/></button></div><div className="strategic-moves">{detail.activity.map((item)=><div key={item.titleKey}><span>●</span><strong>{t(item.titleKey)}<small>{item.description}</small></strong><small>{t(item.timeKey)}</small></div>)}</div></Card></section>
  </div></DashboardLayout>;
}

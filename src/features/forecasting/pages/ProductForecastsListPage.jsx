import { useMemo, useState } from 'react';
import { CalendarDays, MoreVertical, Plus, Search, SlidersHorizontal } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { DemandPredictionTabs } from '../components/DemandPredictionTabs.jsx';
import { AccuracyRing, DemandKpiCard, MiniSparkline, ProductIdentity, TrendBadge } from '../components/DemandShared.jsx';
import { demandProducts, demandRoutePaths, productForecastSummary } from '../config/demandPreviewData.js';
import '../styles/DemandPrediction.css';

export function ProductForecastsListPage() {
  const { t } = useI18n(); const navigate = useNavigate();
  const [query,setQuery]=useState(''); const [category,setCategory]=useState('all'); const [trend,setTrend]=useState('all'); const [status,setStatus]=useState('all');
  const rows=useMemo(()=>demandProducts.filter((item)=>{
    const matchesQuery=`${item.name} ${item.sku}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (category==='all'||item.categoryKey===category) && (trend==='all'||item.tone===trend) && (status==='all'||item.tone===status);
  }),[query,category,trend,status]);
  const clear=()=>{setQuery('');setCategory('all');setTrend('all');setStatus('all')};
  return <BusinessPageContainer wide className="demand-page demand-products-page">
    <PageHeader title={t('demand.products.title')} subtitle={t('demand.products.subtitle')} actions={<><label className="demand-date-control"><CalendarDays size={15}/><select aria-label={t('demand.common.dateRange')}><option>{t('demand.common.next30Days')}</option></select></label><Button leadingIcon={<Plus size={15}/>}>{t('demand.products.addProduct')}</Button></>}/>
    <DemandPredictionTabs t={t}/>
    <section className="demand-kpi-grid demand-product-summary">{productForecastSummary.map((item)=><DemandKpiCard key={item.labelKey} item={item} t={t}/>)}</section>
    <div className="demand-filter-row"><label className="demand-search"><Search size={16}/><input value={query} onChange={(event)=>setQuery(event.target.value)} placeholder={t('demand.filters.searchProducts')} aria-label={t('demand.filters.searchProducts')}/></label><select value={category} onChange={(event)=>setCategory(event.target.value)} aria-label={t('demand.filters.category')}><option value="all">{t('demand.filters.allCategories')}</option>{[...new Set(demandProducts.map((item)=>item.categoryKey))].map((key)=><option value={key} key={key}>{t(key)}</option>)}</select><select value={trend} onChange={(event)=>setTrend(event.target.value)} aria-label={t('demand.filters.trend')}><option value="all">{t('demand.filters.allTrends')}</option><option value="increasing">{t('demand.status.increasing')}</option><option value="decreasing">{t('demand.status.decreasing')}</option></select><select value={status} onChange={(event)=>setStatus(event.target.value)} aria-label={t('demand.filters.status')}><option value="all">{t('demand.filters.allStatuses')}</option><option value="increasing">{t('demand.status.increasing')}</option><option value="decreasing">{t('demand.status.decreasing')}</option></select><button type="button" className="demand-clear" onClick={clear}><SlidersHorizontal size={15}/>{t('demand.filters.clear')}</button></div>
    <section className="demand-table-panel">{rows.length?<div className="demand-table-wrap"><table className="demand-table demand-products-table"><thead><tr><th>#</th><th>{t('demand.table.product')}</th><th>{t('demand.table.category')}</th><th>{t('demand.table.currentStock')}</th><th>{t('demand.table.forecast30')}</th><th>{t('demand.table.change')}</th><th>{t('demand.table.demandTrend')}</th><th>{t('demand.table.accuracy')}</th><th>{t('demand.table.status')}</th><th>{t('demand.table.action')}</th></tr></thead><tbody>{rows.map((product,index)=><tr key={product.id}><td>{index+1}</td><td><ProductIdentity product={product} t={t}/></td><td>{t(product.categoryKey)}</td><td><bdi>{product.stock}</bdi></td><td><bdi>{product.forecast}</bdi></td><td className={product.change>0?'demand-positive':'demand-negative'}><bdi>{product.change>0?'+':''}{product.change}%</bdi></td><td><MiniSparkline values={product.trend} negative={product.change<0}/></td><td><AccuracyRing value={product.accuracy}/></td><td><TrendBadge tone={product.tone} t={t}/></td><td><div className="demand-row-actions"><Button variant="secondary" size="sm" onClick={()=>navigate(demandRoutePaths.products+'/'+product.id)}>{t('demand.common.viewDetails')}</Button><button type="button" className="demand-icon-button" aria-label={t('demand.common.more')}><MoreVertical size={16}/></button></div></td></tr>)}</tbody></table></div>:<EmptyState title={t('demand.products.empty')} />}
      <div className="demand-pagination"><span>{t('demand.products.showing',{count:rows.length,total:demandProducts.length})}</span><div><button aria-label={t('demand.pagination.previous')}>‹</button><button className="is-active">1</button><button>2</button><button>3</button><button>4</button><button aria-label={t('demand.pagination.next')}>›</button></div></div>
    </section>
  </BusinessPageContainer>;
}

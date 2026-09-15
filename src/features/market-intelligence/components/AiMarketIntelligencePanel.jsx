import { ArrowDownRight, ArrowUpRight, BrainCircuit, Smile } from 'lucide-react';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function AiMarketIntelligencePanel({ intelligence, t, localize, formatDate, emptyState }) {
  if (!intelligence) return emptyState;
  return <section className="market-main-ai">
    <div className="market-main-ai__header"><div><span><BrainCircuit size={19} aria-hidden="true" /></span><div><h2>{t('marketMain.ai.title')}</h2><p>{t('marketMain.ai.generated', { date: formatDate(intelligence.generatedAt) })}</p></div></div><DataStatusBadge status={intelligence.dataStatus} /></div>
    <div className="market-main-ai__grid">
      <article className="market-main-ai__insight"><h3>{t('marketMain.ai.insight')}</h3><p>{localize(intelligence.insight)}</p><small>{t('marketMain.ai.confidence', { value: Math.round(intelligence.confidence * 100) })}</small></article>
      <article className="market-main-ai__drivers"><h3>{t('marketMain.ai.drivers')}</h3><div>{intelligence.drivers.map((driver) => <p key={driver.id} className={`is-${driver.direction}`}>{driver.direction === 'positive' ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}<span><small>{t(`marketMain.driverTypes.${driver.type}`)}</small>{localize(driver.text)}</span></p>)}</div></article>
      <article className="market-main-ai__sentiment"><h3><Smile size={16} />{t('marketMain.ai.sentiment')}</h3><strong className={`is-${intelligence.sentiment}`}>{t(`marketMain.sentiments.${intelligence.sentiment}`)}</strong><p>{localize(intelligence.sentimentSummary)}</p></article>
    </div>
  </section>;
}

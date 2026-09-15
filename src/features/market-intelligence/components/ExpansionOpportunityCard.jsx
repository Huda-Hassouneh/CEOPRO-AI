import { Building2, Sparkles } from 'lucide-react';
import Card from '../../../shared/components/ui/Card.jsx';
import DataStatusBadge from '../../../shared/components/ui/DataStatusBadge.jsx';

export function ExpansionOpportunityCard({ opportunity, t, localize, number }) {
  return <Card className="market-main-opportunity">
    <div className="market-main-opportunity__header"><span><Sparkles size={17} /></span><DataStatusBadge status={opportunity.dataStatus} /></div>
    <h3>{localize(opportunity.productName)}</h3>
    <div className="market-main-opportunity__score"><strong>{number(opportunity.opportunityScore)}</strong><span>{t('marketMain.opportunities.score')}</span></div>
    <p>{localize(opportunity.explanation)}</p>
    <div className="market-main-opportunity__companies"><span><Building2 size={14} />{t('marketMain.opportunities.competitorCount', { count: number(opportunity.competitorCount) })}</span><small>{opportunity.competitors.join(' · ')}</small></div>
  </Card>;
}

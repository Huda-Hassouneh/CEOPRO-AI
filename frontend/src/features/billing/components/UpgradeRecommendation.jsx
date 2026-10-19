import { ArrowUpRight, CircleAlert } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';

export function UpgradeRecommendation({ recommendation, onCompare, t }) {
  if (!recommendation) return null;
  return <section className="billing-upgrade-banner"><span><CircleAlert size={21} /></span><div><h3>{t(recommendation.titleKey)}</h3><p>{t(recommendation.descriptionKey, recommendation.values)}</p></div><Button size="sm" trailingIcon={<ArrowUpRight size={14} />} onClick={onCompare}>{t('billing.management.comparePlansAction')}</Button></section>;
}

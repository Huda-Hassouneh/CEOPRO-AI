import { ArrowRight, Sparkles } from 'lucide-react';
import Button from '../../../shared/components/ui/Button.jsx';
export function MarketInsightPanel({ t }) { return <section className="market-panel market-insight-panel"><h2><Sparkles size={18} />{t('market.insight.title')}</h2><p>{t('market.insight.description')}</p><Button variant="outline" size="sm" trailingIcon={<ArrowRight size={14} />}>{t('market.insight.action')}</Button></section>; }

import { NavLink } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';

const tabs = [
  { key: 'overview', path: routePaths.market, labelKey: 'market.tabs.overview', end: true },
  { key: 'leaderboard', path: routePaths.marketLeaderboard, labelKey: 'market.tabs.leaderboard' },
  { key: 'trends', path: routePaths.marketTrends, labelKey: 'market.tabs.trends' },
];

export function MarketTabs() {
  const { t } = useI18n();
  return <nav className="market-tabs" aria-label={t('market.tabs.label')}>{tabs.map((tab) => <NavLink key={tab.key} to={tab.path} end={tab.end}>{t(tab.labelKey)}</NavLink>)}</nav>;
}

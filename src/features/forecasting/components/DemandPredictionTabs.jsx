import { NavLink } from 'react-router-dom';
import { demandRoutePaths } from '../config/demandPreviewData.js';

export function DemandPredictionTabs({ t }) {
  const tabs = [
    ['demand.tabs.overview', demandRoutePaths.overview, true],
    ['demand.tabs.products', demandRoutePaths.products, false],
    ['demand.tabs.inventory', demandRoutePaths.inventory, false],
  ];

  return <nav className="demand-tabs" aria-label={t('demand.tabs.label')}>
    {tabs.map(([labelKey, to, end]) => <NavLink key={to} to={to} end={end}>{t(labelKey)}</NavLink>)}
  </nav>;
}

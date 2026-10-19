import {
  BarChart3,
  BrainCircuit,
  Cable,
  FileBarChart,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Package,
  Settings,
  Tag,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { routePaths } from '../../app/router/routePaths.js';

// Sales is not a separate destination: sales history, trends and forecasts
// live with each product (Products -> a product), today's sales are on the
// Command Center, and "Record sale" is an action on Products.
export const businessNavigationGroups = [
  {
    key: 'overview',
    labelKey: 'businessShell.navigation.groups.overview',
    items: [
      { key: 'dashboard', labelKey: 'businessShell.navigation.dashboard', path: routePaths.dashboard, icon: LayoutDashboard },
    ],
  },
  {
    key: 'business',
    labelKey: 'businessShell.navigation.groups.business',
    items: [
      { key: 'products', labelKey: 'businessShell.navigation.products', path: routePaths.products, icon: Package, activePaths: [routePaths.sales] },
      { key: 'forecasts', labelKey: 'businessShell.navigation.forecasts', path: routePaths.forecasts, icon: TrendingUp },
      { key: 'pricing', labelKey: 'businessShell.navigation.pricing', path: routePaths.pricing, icon: Tag },
      { key: 'reports', labelKey: 'businessShell.navigation.reports', path: routePaths.reports, icon: FileBarChart },
    ],
  },
  {
    key: 'market',
    labelKey: 'businessShell.navigation.groups.market',
    items: [
      { key: 'market', labelKey: 'businessShell.navigation.market', path: routePaths.market, icon: BarChart3 },
      { key: 'marketing', labelKey: 'businessShell.navigation.marketing', path: routePaths.marketing, icon: Megaphone },
    ],
  },
  {
    key: 'intelligence',
    labelKey: 'businessShell.navigation.groups.intelligence',
    items: [
      { key: 'rag', labelKey: 'businessShell.navigation.rag', path: routePaths.aiAdvisor, icon: BrainCircuit },
      { key: 'connectData', labelKey: 'businessShell.navigation.connectData', path: routePaths.connectData, icon: Cable },
    ],
  },
];

export const businessPrimaryNavigation = businessNavigationGroups.flatMap((group) => group.items);

// Account destinations live in the profile menu of the top navigation.
export const businessSecondaryNavigation = [
  { key: 'settings', labelKey: 'businessShell.navigation.settings', path: routePaths.settings, icon: Settings },
  { key: 'billing', labelKey: 'businessShell.navigation.billing', path: routePaths.billing, icon: WalletCards },
  { key: 'logout', labelKey: 'businessShell.navigation.logout', path: null, icon: LogOut },
];

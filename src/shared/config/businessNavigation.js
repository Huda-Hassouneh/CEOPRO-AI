import {
  BarChart3,
  Bot,
  BrainCircuit,
  Cable,
  LayoutDashboard,
  LogOut,
  Settings,
  TrendingUp,
  WalletCards,
} from 'lucide-react';
import { routePaths } from '../../app/router/routePaths.js';

export const businessPrimaryNavigation = [
  { key: 'dashboard', labelKey: 'businessShell.navigation.dashboard', path: routePaths.dashboard, icon: LayoutDashboard },
  { key: 'market', labelKey: 'businessShell.navigation.market', path: routePaths.market, icon: BarChart3 },
  { key: 'forecasts', labelKey: 'businessShell.navigation.forecasts', path: routePaths.forecasts, icon: TrendingUp },
  { key: 'rag', labelKey: 'businessShell.navigation.rag', path: routePaths.aiAdvisor, icon: BrainCircuit },
  { key: 'connectData', labelKey: 'businessShell.navigation.connectData', path: routePaths.connectData, icon: Cable },
];

export const businessSecondaryNavigation = [
  { key: 'settings', labelKey: 'businessShell.navigation.settings', path: routePaths.settings, icon: Settings },
  { key: 'billing', labelKey: 'businessShell.navigation.billing', path: routePaths.billing, icon: WalletCards },
  { key: 'logout', labelKey: 'businessShell.navigation.logout', path: null, icon: LogOut },
];

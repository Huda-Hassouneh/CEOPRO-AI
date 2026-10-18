import { Lock } from 'lucide-react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../features/auth/store/authStore.js';
import { useSubscription } from '../../features/billing/hooks/useSubscription.js';
import { useI18n } from '../providers/I18nProvider.jsx';
import { DashboardLayout } from '../layouts/DashboardLayout.jsx';
import { ApexButton, Panel, StateBlock } from '../../shared/components/apex/Apex.jsx';
import { routePaths } from './routePaths.js';

// Screens that belong to a plan module (backend usage_plan_entitlements;
// the API refuses them with 402 NOT_INCLUDED on plans without it).
const GATED = [
  ['/market', 'competitor_management'],
  ['/demand', 'demand_prediction'],
];

export function moduleForPath(pathname) {
  return GATED.find(([prefix]) => pathname === prefix || pathname.startsWith(`${prefix}/`))?.[1] || null;
}

// Shows what the plan doesn't include instead of a screen full of errors.
// While the plan is loading, or if it can't be read, the screen renders
// normally - the API still enforces the plan either way.
export function PlanGate({ children }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const { t } = useI18n();
  const companyId = useAuthStore((state) => state.tenantId);
  const module = moduleForPath(pathname);
  const { data } = useSubscription(companyId, { enabled: Boolean(module && companyId), staleTime: 60_000 });
  if (!module || !data?.available) return children;
  const inactive = data.hasAccess === false;
  if (!inactive && (data.entitlements || []).includes(module)) return children;
  return (
    <DashboardLayout>
      <Panel>
        <StateBlock
          title={inactive ? t('billing.gate.inactiveTitle') : t('billing.gate.title', { feature: t(`billing.modules.${module}`) })}
          description={inactive ? t('billing.gate.inactiveBody') : t('billing.gate.body')}
          action={<ApexButton icon={Lock} onClick={() => navigate(routePaths.billing)}>{t('billing.gate.action')}</ApexButton>}
        />
      </Panel>
    </DashboardLayout>
  );
}

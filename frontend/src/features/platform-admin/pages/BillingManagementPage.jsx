import { BillingCatalogPage } from '../../billing/pages/BillingCatalogPage.jsx';
import { useAdmin } from '../components/AdminContext.jsx';
import { platformBillingCatalogApi } from '../../platform/platformBillingCatalogApi.js';
import { useSearchParams } from 'react-router-dom';
import { PlatformBillingAdmin } from '../../platform/PlatformBillingAdminPython.jsx';

export function BillingManagementPage() {
  const admin = useAdmin();
  const [params] = useSearchParams();
  // Keep existing Python policy/quote evidence links inside the original shell.
  if (params.get('python') === '1') return <PlatformBillingAdmin />;
  return (
    <BillingCatalogPage
      api={platformBillingCatalogApi}
      platformMode
      canManage={admin.can('billing.manage')}
      canManagePricing={admin.can('billing.pricing.manage')}
    />
  );
}

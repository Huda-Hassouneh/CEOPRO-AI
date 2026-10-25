import { BillingCatalogPage } from '../../billing/pages/BillingCatalogPage.jsx';
import { useAdmin } from '../components/AdminContext.jsx';
import { platformBillingCatalogApi } from '../../platform/platformBillingCatalogApi.js';

export function BillingManagementPage() {
  const admin = useAdmin();
  return (
    <BillingCatalogPage
      api={platformBillingCatalogApi}
      platformMode
      canManage={admin.can('billing.manage')}
      canManagePricing={admin.can('billing.pricing.manage')}
    />
  );
}

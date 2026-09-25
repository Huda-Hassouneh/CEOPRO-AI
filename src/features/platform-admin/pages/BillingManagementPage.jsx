import { BillingCatalogPage } from '../../billing/pages/BillingCatalogPage.jsx';
import { useAdmin } from '../components/AdminContext.jsx';
import { platformBillingApi } from '../api/platformBillingApi.js';

export function BillingManagementPage() {
  const admin = useAdmin();

  return (
    <BillingCatalogPage
      api={platformBillingApi}
      platformMode
      canManage={admin.can('billing.manage')}
      canManagePricing={admin.can('billing.pricing.manage')}
    />
  );
}

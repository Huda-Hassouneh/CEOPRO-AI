import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { useI18n } from '../../app/providers/I18nProvider.jsx';
import { platformApi } from './platformApi.js';
import { PlatformBillingAdmin as PythonBillingAdmin } from './PlatformBillingAdminPython.jsx';
import { BillingCatalogPage } from '../billing/pages/BillingCatalogPage.jsx';
import { platformBillingCatalogApi } from './platformBillingCatalogApi.js';
import { useAuthStore, selectIsAuthenticated } from '../auth/store/authStore.js';
import './platform.css';

export function PlatformBillingAdmin() {
  const [params] = useSearchParams();
  const { locale, t } = useI18n();
  const authenticated = useAuthStore(selectIsAuthenticated);
  const hydrated = useAuthStore((state) => state.isHydrated);
  const actor = useAuthStore((state) => state.user?.id);
  const who = useQuery({ queryKey: ['platform', actor, 'me'], queryFn: platformApi.me, enabled: hydrated && authenticated, retry: false });

  if (params.get('python') === '1') return <PythonBillingAdmin />;
  if (!hydrated || (authenticated && who.isPending)) return <main className="billing-management-page billing-catalog-page" aria-busy="true" />;
  if (!authenticated || who.error || who.data?.role !== 'owner') {
    return <main className="billing-management-page billing-catalog-page" role="alert">{locale === 'ar' ? 'صلاحية مالك المنصة مطلوبة.' : 'Platform Owner permission is required.'}</main>;
  }

  return <>
    <div className="platform-billing-authority-link" dir={locale === 'ar' ? 'rtl' : 'ltr'}>
      <Link to="/platform/billing?python=1">{t('billing.catalog.customPlans.pricingPolicy.openOwnerBilling')}</Link>
    </div>
    <BillingCatalogPage api={platformBillingCatalogApi} platformMode canManage={false} canManagePricing={false} />
  </>;
}
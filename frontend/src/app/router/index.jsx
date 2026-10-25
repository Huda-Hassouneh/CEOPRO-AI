import { createBrowserRouter, Navigate, useParams } from 'react-router-dom';
import { routePaths } from './routePaths.js';
import { page } from './lazyPage.jsx';
import { ProtectedRoute } from './ProtectedRoute.jsx';
import { GuestRoute } from './GuestRoute.jsx';
import { PublicLayout } from '../layouts/PublicLayout.jsx';
import { AuthLayout } from '../layouts/AuthLayout.jsx';
import { DashboardLayout } from '../layouts/DashboardLayout.jsx';
import { AppErrorPage } from '../../shared/components/feedback/ErrorBoundary.jsx';
import { platformAdminRoute } from '../../features/platform-admin/routes.jsx';

import { LoginPage } from '../../features/auth/pages/LoginPage.jsx';
import { SignupPage } from '../../features/auth/pages/SignupPage.jsx';
import { ForgotPasswordPage } from '../../features/auth/pages/ForgotPasswordPage.jsx';
import { ResetPasswordPage } from '../../features/auth/pages/ResetPasswordPage.jsx';
import { VerifyEmailPage } from '../../features/auth/pages/VerifyEmailPage.jsx';
import { VerificationCodePage } from '../../features/auth/pages/VerificationCodePage.jsx';





const SetupPage = page(() => import('../../features/onboarding/pages/SetupPage.jsx').then((m) => ({ default: m.SetupPage })));
const CreateWorkspacePage = page(() => import('../../features/workspaces/pages/CreateWorkspacePage.jsx').then((m) => ({ default: m.CreateWorkspacePage })));
const InvitationPage = page(() => import('../../features/auth/pages/InvitationPage.jsx').then((m) => ({ default: m.InvitationPage })));
const WelcomePage = page(() => import('../../features/system/pages/WelcomePage.jsx'));
const CommandCenterPage = page(() => import('../../features/dashboard/pages/CommandCenterPage.jsx').then((m) => ({ default: m.CommandCenterPage })));
const ProductsListPage = page(() => import('../../features/products/pages/ProductsListPage.jsx').then((m) => ({ default: m.ProductsListPage })));
const ProductFormPage = page(() => import('../../features/products/pages/ProductFormPage.jsx').then((m) => ({ default: m.ProductFormPage })));
const PriceComparisonReportPage = page(() => import('../../features/pricing/pages/PriceComparisonReportPage.jsx').then((m) => ({ default: m.PriceComparisonReportPage })));
const PricingPage = page(() => import('../../features/pricing/pages/PricingPage.jsx').then((m) => ({ default: m.PricingPage })));
const ProductDetailPage = page(() => import('../../features/products/pages/ProductDetailPage.jsx').then((m) => ({ default: m.ProductDetailPage })));
const ProductHubPage = page(() => import('../../features/products/pages/ProductHubPage.jsx').then((m) => ({ default: m.ProductHubPage })));
const CompetitorLandscapePage = page(() => import('../../features/market-intelligence/pages/CompetitorLandscapePage.jsx').then((m) => ({ default: m.CompetitorLandscapePage })));
const AddCompetitorPage = page(() => import('../../features/market-intelligence/pages/AddCompetitorPage.jsx').then((m) => ({ default: m.AddCompetitorPage })));
const SearchScopePage = page(() => import('../../features/market-intelligence/pages/SearchScopePage.jsx').then((m) => ({ default: m.SearchScopePage })));
const PendingSourcesPage = page(() => import('../../features/market-intelligence/pages/PendingSourcesPage.jsx').then((m) => ({ default: m.PendingSourcesPage })));
const IndustryMarketTrendsPage = page(() => import('../../features/market-intelligence/pages/IndustryMarketTrendsPage.jsx').then((m) => ({ default: m.IndustryMarketTrendsPage })));
const CompetitorProfileDetailPage = page(() => import('../../features/market-intelligence/pages/CompetitorProfileDetailPage.jsx').then((m) => ({ default: m.CompetitorProfileDetailPage })));
const MarketLeaderboardPage = page(() => import('../../features/market-intelligence/pages/MarketLeaderboardPage.jsx').then((m) => ({ default: m.MarketLeaderboardPage })));
const DemandPredictionOverviewPage = page(() => import('../../features/forecasting/pages/DemandPredictionOverviewPage.jsx').then((m) => ({ default: m.DemandPredictionOverviewPage })));
const RagAssistantPage = page(() => import('../../features/knowledge-base/pages/RagAssistantPage.jsx').then((m) => ({ default: m.RagAssistantPage })));
const MarketingStudioPage = page(() => import('../../features/marketing/pages/MarketingStudioPage.jsx'));
const SettingsPage = page(() => import('../../features/settings/pages/SettingsPage.jsx'));
const ConnectDataPage = page(() => import('../../features/data-connections/pages/ConnectDataPage.jsx').then((m) => ({ default: m.ConnectDataPage })));
const UnifiedReportsCenterPage = page(() => import('../../features/reports/pages/UnifiedReportsCenterPage.jsx'));
const PlansSubscriptionPage = page(() => import('../../features/billing/pages/PlansSubscriptionPage.jsx').then((m) => ({ default: m.PlansSubscriptionPage })));
const OnboardingPlanSelectionPage = page(() => import('../../features/billing/pages/OnboardingPlanSelectionPage.jsx').then((m) => ({ default: m.OnboardingPlanSelectionPage })));
const OnboardingPaymentPage = page(() => import('../../features/billing/pages/OnboardingPaymentPage.jsx').then((m) => ({ default: m.OnboardingPaymentPage })));
const CustomPlanBuilderPage = page(() => import('../../features/billing/pages/CustomPlanBuilderPage.jsx').then((m) => ({ default: m.CustomPlanBuilderPage })));
const CustomPlanQuotePage = page(() => import('../../features/billing/pages/CustomPlanQuotePage.jsx').then((m) => ({ default: m.CustomPlanQuotePage })));

const LegacyForecastProductRedirect = () => {
  const { productId } = useParams();
  return <Navigate to={`/products/${productId}`} replace />;
};

const ProductPageRedirect = () => {
  const { productId } = useParams();
  return <Navigate to={`/products/${productId}`} replace />;
};

const routes = [
  // Old billing and onboarding-plan addresses: payment now happens on
  // Stripe-hosted Checkout from Billing.
  ...['/choose-plan', '/checkout', '/payment-success', '/payment-failed', '/billing/checkout', '/onboarding/*']
    .map((path) => ({ path, element: <Navigate to={path.startsWith('/onboarding') ? '/onboarding' : '/billing'} replace /> })),
  platformAdminRoute,
  { path: '/platform/billing', element: <Navigate to="/admin/billing" replace /> },
  { path: '/platform', element: <Navigate to="/admin" replace /> },
  { path: '/platform/invitations/:token', lazy: async () => ({ Component: (await import('../../features/platform/PlatformInvitation.jsx')).PlatformInvitation }) },
  {
    path: routePaths.welcome,
    element: (
      <PublicLayout hideHeader>
        <WelcomePage />
      </PublicLayout>
    ),
  },
  {
    path: routePaths.terms,
    lazy: async () => { const { LegalPage } = await import('../../features/legal/pages/LegalPage.jsx'); return { Component: () => <LegalPage kind="terms" /> }; },
  },
  {
    path: routePaths.privacy,
    lazy: async () => { const { LegalPage } = await import('../../features/legal/pages/LegalPage.jsx'); return { Component: () => <LegalPage kind="privacy" /> }; },
  },
  {
    path: routePaths.landing,
    lazy: async () => ({ Component: (await import('../../features/landing/pages/LandingPage.jsx')).default }),
  },
  {
    path: routePaths.login,
    element: (
      <GuestRoute>
        <AuthLayout brand>
          <LoginPage />
        </AuthLayout>
      </GuestRoute>
    ),
  },
  {
    path: routePaths.signup,
    element: (
      <GuestRoute>
        <AuthLayout brand wide>
          <SignupPage />
        </AuthLayout>
      </GuestRoute>
    ),
  },
  {
    path: routePaths.createAccount,
    element: <Navigate to={routePaths.signup} replace />,
  },
  {
    path: routePaths.completeRegistrationGoogle,
    element: <Navigate to={routePaths.signup} replace />,
  },
  {
    path: routePaths.forgotPassword,
    element: (
      <AuthLayout brand>
        <ForgotPasswordPage />
      </AuthLayout>
    ),
  },
  {
    path: routePaths.verifyCode,
    element: (
      <AuthLayout brand>
        <VerificationCodePage />
      </AuthLayout>
    ),
  },
  {
    path: routePaths.resetPassword,
    element: (
      <AuthLayout brand>
        <ResetPasswordPage />
      </AuthLayout>
    ),
  },
  {
    path: routePaths.verifyEmail,
    element: (
      <AuthLayout brand>
        <VerifyEmailPage />
      </AuthLayout>
    ),
  },
  {
    path: `${routePaths.invitation}/:token?`,
    element: (
      <AuthLayout brand wide>
        <InvitationPage />
      </AuthLayout>
    ),
  },
  {
    path: routePaths.onboarding,
    element: <ProtectedRoute><SetupPage /></ProtectedRoute>,
  },
  {
    path: routePaths.newWorkspace,
    element: <ProtectedRoute><CreateWorkspacePage /></ProtectedRoute>,
  },
  {
    path: routePaths.onboardingPlan,
    element: <ProtectedRoute><DashboardLayout><OnboardingPlanSelectionPage /></DashboardLayout></ProtectedRoute>,
  },
  { path: routePaths.onboardingPlanPayment, element: <ProtectedRoute><DashboardLayout><OnboardingPaymentPage /></DashboardLayout></ProtectedRoute> },
  { path: routePaths.customPlanBuilder, element: <ProtectedRoute><DashboardLayout><CustomPlanBuilderPage /></DashboardLayout></ProtectedRoute> },
  { path: routePaths.customPlanQuote, element: <ProtectedRoute><DashboardLayout><CustomPlanQuotePage /></DashboardLayout></ProtectedRoute> },
  {
    path: routePaths.billing,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <PlansSubscriptionPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.dashboard,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <CommandCenterPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.products,
    element: <ProtectedRoute><ProductsListPage /></ProtectedRoute>,
  },
  {
    path: routePaths.productNew,
    element: <ProtectedRoute><ProductFormPage /></ProtectedRoute>,
  },
  {
    path: routePaths.productEdit,
    element: <ProtectedRoute><ProductFormPage /></ProtectedRoute>,
  },
  {
    // Sales live with each product (its page) and "Record sale" on Products.
    path: routePaths.sales,
    element: <Navigate to={routePaths.products} replace />,
  },
  {
    path: routePaths.productDetail,
    element: <ProtectedRoute><ProductHubPage /></ProtectedRoute>,
  },
  {
    path: routePaths.pricing,
    element: <ProtectedRoute><PricingPage /></ProtectedRoute>,
  },
  {
    path: routePaths.pricingReport,
    element: <ProtectedRoute><PriceComparisonReportPage /></ProtectedRoute>,
  },
  {
    path: routePaths.market,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <CompetitorLandscapePage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    // One Competitors screen: the landscape lists every competitor.
    path: routePaths.marketCompetitors,
    element: <Navigate to={routePaths.market} replace />,
  },
  {
    path: routePaths.marketCompetitorDetail,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <CompetitorProfileDetailPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.marketCompetitorProductDetail,
    element: <ProtectedRoute><ProductDetailPage /></ProtectedRoute>,
  },
  {
    path: routePaths.marketAddCompetitor,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <AddCompetitorPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.marketSearchScope,
    element: <ProtectedRoute><SearchScopePage /></ProtectedRoute>,
  },
  {
    path: routePaths.marketPendingSources,
    element: <ProtectedRoute><PendingSourcesPage /></ProtectedRoute>,
  },
  {
    // Opportunity analysis isn't built (no market-size or demand-growth
    // data); the old screen only said so. Back to Competitors.
    path: routePaths.marketOpportunities,
    element: <Navigate to={routePaths.market} replace />,
  },
  {
    path: routePaths.marketOpportunityDetail,
    element: <Navigate to={routePaths.market} replace />,
  },
  {
    path: routePaths.marketLeaderboard,
    element: <ProtectedRoute><MarketLeaderboardPage /></ProtectedRoute>,
  },
  {
    path: routePaths.marketTrends,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <IndustryMarketTrendsPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    // Reports live in Reports.
    path: routePaths.marketReports,
    element: <Navigate to={routePaths.reports} replace />,
  },
  {
    path: routePaths.forecasts,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <DemandPredictionOverviewPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    // Preview/stub page (fixed demo products or a placeholder) - real
    // forecasts and restock advice live on /demand.
    path: routePaths.forecastDeepDive,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    // Preview/stub page (fixed demo products or a placeholder) - real
    // forecasts and restock advice live on /demand.
    path: routePaths.forecastProducts,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    // A product's forecast is part of its page now.
    path: routePaths.forecastProductDetail,
    element: <ProductPageRedirect />,
  },
  {
    // Preview/stub page (fixed demo products or a placeholder) - real
    // forecasts and restock advice live on /demand.
    path: routePaths.forecastInventory,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    // Preview/stub page (fixed demo products or a placeholder) - real
    // forecasts and restock advice live on /demand.
    path: routePaths.forecastEmpty,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    // Preview/stub page (fixed demo products or a placeholder) - real
    // forecasts and restock advice live on /demand.
    path: routePaths.forecastAccuracy,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    path: routePaths.legacyForecasts,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    path: routePaths.legacyForecastProducts,
    element: <Navigate to={routePaths.forecasts} replace />,
  },
  {
    path: routePaths.legacyForecastProductDetail,
    element: <LegacyForecastProductRedirect />,
  },
  {
    path: routePaths.aiAdvisor,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <RagAssistantPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.aiAdvisorChat,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <RagAssistantPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.connectData,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <ConnectDataPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.marketing,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <MarketingStudioPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.reports,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <UnifiedReportsCenterPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.settings,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <SettingsPage />
        </DashboardLayout>
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.settingsSecurity,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=security`} replace />
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.settingsTeam,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=team`} replace />
      </ProtectedRoute>
    ),
  },
  {
    path: routePaths.settingsIntegrations,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=company`} replace />
      </ProtectedRoute>
    ),
  },
  {
    path: '*',
    element: <AppErrorPage notFound />,
  },
];

// One root route so every screen shares the same error screen instead of
// React Router's developer error page.
export const router = createBrowserRouter([{ errorElement: <AppErrorPage />, children: routes }]);



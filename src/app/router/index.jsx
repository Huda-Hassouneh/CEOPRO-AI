import { createBrowserRouter, Navigate, useParams } from "react-router-dom";
import { routePaths } from "./routePaths.js";
import { ProtectedRoute } from "./ProtectedRoute.jsx";
import { GuestRoute } from "./GuestRoute.jsx";
import { OnboardingGuard } from "./OnboardingGuard.jsx";
import { PublicLayout } from "../layouts/PublicLayout.jsx";
import { AuthLayout } from "../layouts/AuthLayout.jsx";
import { OnboardingLayout } from "../layouts/OnboardingLayout.jsx";
import { DashboardLayout } from "../layouts/DashboardLayout.jsx";
import { platformAdminRoute } from "../../features/platform-admin/routes.jsx";

import { LoginPage } from "../../features/auth/pages/LoginPage.jsx";
import { SignupPage } from "../../features/auth/pages/SignupPage.jsx";
import { ForgotPasswordPage } from "../../features/auth/pages/ForgotPasswordPage.jsx";
import { ResetPasswordPage } from "../../features/auth/pages/ResetPasswordPage.jsx";
import { VerifyEmailPage } from "../../features/auth/pages/VerifyEmailPage.jsx";
import { VerificationCodePage } from "../../features/auth/pages/VerificationCodePage.jsx";
import { InvitationPage } from "../../features/auth/pages/InvitationPage.jsx";

import WelcomePage from "../../features/system/pages/WelcomePage.jsx";

import { OnboardingWelcomePage } from "../../features/onboarding/pages/OnboardingWelcomePage.jsx";
import { OnboardingIndustryPage } from "../../features/onboarding/pages/OnboardingIndustryPage.jsx";
import { OnboardingBusinessSizePage } from "../../features/onboarding/pages/OnboardingBusinessSizePage.jsx";
import { OnboardingRegionalPreferencesPage } from "../../features/onboarding/pages/OnboardingRegionalPreferencesPage.jsx";
import { OnboardingDataSourcesPage } from "../../features/onboarding/pages/OnboardingDataSourcesPage.jsx";
import { OnboardingBusinessSystemPage } from "../../features/onboarding/pages/OnboardingBusinessSystemPage.jsx";
import { OnboardingBusinessSystemPlaceholderPage } from "../../features/onboarding/pages/OnboardingBusinessSystemPlaceholderPage.jsx";
import { OnboardingConnectDatabasePage } from "../../features/onboarding/pages/OnboardingConnectDatabasePage.jsx";
import { OnboardingUploadDocumentsPage } from "../../features/onboarding/pages/OnboardingUploadDocumentsPage.jsx";
import { OnboardingGoalsPage } from "../../features/onboarding/pages/OnboardingGoalsPage.jsx";
import { OnboardingPlanSelectionPage } from "../../features/onboarding/pages/OnboardingPlanSelectionPage.jsx";
import { OnboardingCustomPlanPage } from "../../features/onboarding/pages/OnboardingCustomPlanPage.jsx";
import { OnboardingPaymentPage } from "../../features/onboarding/pages/OnboardingPaymentPage.jsx";
import { OnboardingSubscriptionSuccessPage } from "../../features/onboarding/pages/OnboardingSubscriptionSuccessPage.jsx";
import { OnboardingSubscriptionFailedPage } from "../../features/onboarding/pages/OnboardingSubscriptionFailedPage.jsx";

import { DashboardHomePage } from "../../features/dashboard/pages/DashboardHomePage.jsx";
import { ProductDetailPage } from "../../features/products/pages/ProductDetailPage.jsx";
import { MarketIntelligenceOverviewPage } from "../../features/market-intelligence/pages/MarketIntelligenceOverviewPage.jsx";
import { CompetitorsPage } from "../../features/market-intelligence/pages/CompetitorsPage.jsx";
import { AddCompetitorPage } from "../../features/market-intelligence/pages/AddCompetitorPage.jsx";
import { IndustryMarketTrendsPage } from "../../features/market-intelligence/pages/IndustryMarketTrendsPage.jsx";
import { MarketIntelligenceReportsPage } from "../../features/market-intelligence/pages/MarketIntelligenceReportsPage.jsx";
import { CompetitorProfileDetailPage } from "../../features/market-intelligence/pages/CompetitorProfileDetailPage.jsx";
import {
  MarketOpportunitiesPage,
  OpportunityDetailPage
} from "../../features/market-intelligence/pages/MarketOpportunitiesPage.jsx";
import { MarketLeaderboardPage } from "../../features/market-intelligence/pages/MarketLeaderboardPage.jsx";
import { DemandPredictionOverviewPage } from "../../features/forecasting/pages/DemandPredictionOverviewPage.jsx";
import { ForecastDeepDivePage } from "../../features/forecasting/pages/ForecastDeepDivePage.jsx";
import { ProductForecastsListPage } from "../../features/forecasting/pages/ProductForecastsListPage.jsx";
import { ProductForecastDetailPage } from "../../features/forecasting/pages/ProductForecastDetailPage.jsx";
import { InventoryRecommendationsPage } from "../../features/forecasting/pages/InventoryRecommendationsPage.jsx";
import { DemandPredictionEmptyPage } from "../../features/forecasting/pages/DemandPredictionEmptyPage.jsx";
import { ModelAccuracyPage } from "../../features/forecasting/pages/ModelAccuracyPage.jsx";
import { RagAssistantPage } from "../../features/knowledge-base/pages/RagAssistantPage.jsx";
import MarketingStudioPage from "../../features/marketing/pages/MarketingStudioPage.jsx";
import SettingsPage from "../../features/settings/pages/SettingsPage.jsx";
import { ConnectDataPage } from "../../features/data-connections/pages/ConnectDataPage.jsx";
import UnifiedReportsCenterPage from "../../features/reports/pages/UnifiedReportsCenterPage.jsx";
import DesignSystemPage from "../../features/design-system/pages/DesignSystemPage.jsx";

import { ChoosePlanPage } from "../../features/billing/pages/ChoosePlanPage.jsx";
import { CheckoutPage } from "../../features/billing/pages/CheckoutPage.jsx";
import { PaymentSuccessPage } from "../../features/billing/pages/PaymentSuccessPage.jsx";
import { PaymentFailedPage } from "../../features/billing/pages/PaymentFailedPage.jsx";
import { PlansSubscriptionPage } from "../../features/billing/pages/PlansSubscriptionPage.jsx";
import { BillingCheckoutPage } from "../../features/billing/pages/BillingCheckoutPage.jsx";
import { BillingCustomPlanPage } from "../../features/billing/pages/BillingCustomPlanPage.jsx";
import { CustomPlanOfferPage } from "../../features/billing/pages/CustomPlanOfferPage.jsx";
import { FeatureRouteGuard } from "../../features/billing/components/FeatureRouteGuard.jsx";

const LegacyForecastProductRedirect = () => {
  const { productId } = useParams();
  return <Navigate to={`/demand/products/${productId}`} replace />;
};

export const router = createBrowserRouter([
  platformAdminRoute,
  {
    path: routePaths.welcome,
    element: (
      <PublicLayout hideHeader>
        <WelcomePage />
      </PublicLayout>
    )
  },
  {
    path: routePaths.designSystem,
    element: (
      <PublicLayout>
        <DesignSystemPage />
      </PublicLayout>
    )
  },
  {
    path: routePaths.landing,
    lazy: async () => ({
      Component: (await import("../../features/landing/pages/LandingPage.jsx"))
        .default
    })
  },
  {
    path: routePaths.login,
    element: (
      <GuestRoute>
        <AuthLayout brand brandLabel="CEO PRO">
          <LoginPage />
        </AuthLayout>
      </GuestRoute>
    )
  },
  {
    path: routePaths.signup,
    element: (
      <GuestRoute>
        <AuthLayout brand wide>
          <SignupPage />
        </AuthLayout>
      </GuestRoute>
    )
  },
  {
    path: routePaths.createAccount,
    element: <Navigate to={routePaths.signup} replace />
  },
  {
    path: routePaths.completeRegistrationGoogle,
    element: (
      <Navigate
        to={routePaths.signup}
        replace
        state={{ authIntent: "google-registration" }}
      />
    )
  },
  {
    path: routePaths.forgotPassword,
    element: (
      <AuthLayout brand>
        <ForgotPasswordPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.verifyCode,
    element: (
      <AuthLayout brand>
        <VerificationCodePage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.resetPassword,
    element: (
      <AuthLayout brand>
        <ResetPasswordPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.verifyEmail,
    element: (
      <AuthLayout brand>
        <VerifyEmailPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.invitation,
    element: (
      <AuthLayout brand brandLabel="CEO PRO" wide>
        <InvitationPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.choosePlan,
    element: (
      <PublicLayout>
        <ChoosePlanPage />
      </PublicLayout>
    )
  },
  {
    path: routePaths.checkout,
    element: (
      <AuthLayout>
        <CheckoutPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.paymentSuccess,
    element: (
      <AuthLayout>
        <OnboardingSubscriptionSuccessPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.paymentFailed,
    element: (
      <AuthLayout>
        <OnboardingSubscriptionFailedPage />
      </AuthLayout>
    )
  },
  {
    path: routePaths.onboardingWelcome,
    element: <OnboardingWelcomePage />
  },
  {
    path: routePaths.billing,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <PlansSubscriptionPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.billingPlans,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <ChoosePlanPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.billingCheckout,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <BillingCheckoutPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.billingCustomPlan,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <BillingCustomPlanPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.billingCatalog,
    element: <Navigate to={routePaths.platformBilling} replace />
  },
  {
    path: routePaths.customPlanOffer,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <CustomPlanOfferPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.onboardingRegion,
    element: (
      <OnboardingGuard requiredStep={1}>
        <OnboardingLayout>
          <OnboardingRegionalPreferencesPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingIndustry,
    element: (
      <OnboardingGuard requiredStep={2}>
        <OnboardingLayout>
          <OnboardingIndustryPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingBusiness,
    element: (
      <OnboardingGuard requiredStep={3}>
        <OnboardingLayout>
          <OnboardingBusinessSizePage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingObjectives,
    element: (
      <OnboardingGuard requiredStep={4}>
        <OnboardingLayout>
          <OnboardingGoalsPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingPlan,
    element: (
      <OnboardingGuard requiredStep={5}>
        <OnboardingLayout>
          <OnboardingPlanSelectionPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingPlanCustom,
    element: (
      <OnboardingGuard requiredStep={5}>
        <OnboardingLayout>
          <OnboardingCustomPlanPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingPlanPayment,
    element: (
      <OnboardingGuard requiredStep={5}>
        <OnboardingLayout>
          <OnboardingPaymentPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingPlanSuccess,
    element: (
      <OnboardingGuard requiredStep={5}>
        <OnboardingLayout>
          <OnboardingSubscriptionSuccessPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingPlanFailed,
    element: (
      <OnboardingGuard requiredStep={5}>
        <OnboardingLayout>
          <OnboardingSubscriptionFailedPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectData,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingDataSourcesPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectDataUpload,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingUploadDocumentsPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectDataBusinessSystem,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingBusinessSystemPage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectDataDatabase,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingConnectDatabasePage />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectDataPos,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingBusinessSystemPlaceholderPage system="pos" />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.onboardingConnectDataErp,
    element: (
      <OnboardingGuard requiredStep={6}>
        <OnboardingLayout>
          <OnboardingBusinessSystemPlaceholderPage system="erp" />
        </OnboardingLayout>
      </OnboardingGuard>
    )
  },
  {
    path: routePaths.dashboard,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="dashboard_analytics">
          <DashboardLayout>
            <DashboardHomePage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.market,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <DashboardLayout>
            <MarketIntelligenceOverviewPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketCompetitors,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes={["market_intelligence", "competitor_management"]}>
          <DashboardLayout>
            <CompetitorsPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketCompetitorDetail,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes={["market_intelligence", "competitor_management"]}>
          <DashboardLayout>
            <CompetitorProfileDetailPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketCompetitorProductDetail,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <ProductDetailPage />
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketAddCompetitor,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes={["market_intelligence", "competitor_management"]}>
          <DashboardLayout>
            <AddCompetitorPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketOpportunities,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <MarketOpportunitiesPage />
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketOpportunityDetail,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <OpportunityDetailPage />
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketLeaderboard,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <MarketLeaderboardPage />
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketTrends,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <DashboardLayout>
            <IndustryMarketTrendsPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketReports,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="market_intelligence">
          <DashboardLayout>
            <MarketIntelligenceReportsPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecasts,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <DemandPredictionOverviewPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastDeepDive,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <ForecastDeepDivePage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastProducts,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <ProductForecastsListPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastProductDetail,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <ProductForecastDetailPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastInventory,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes={["demand_prediction", "inventory_intelligence"]}>
          <DashboardLayout>
            <InventoryRecommendationsPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastEmpty,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <DemandPredictionEmptyPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.forecastAccuracy,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="demand_prediction">
          <DashboardLayout>
            <ModelAccuracyPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.legacyForecasts,
    element: <Navigate to={routePaths.forecasts} replace />
  },
  {
    path: routePaths.legacyForecastProducts,
    element: <Navigate to={routePaths.forecastProducts} replace />
  },
  {
    path: routePaths.legacyForecastProductDetail,
    element: <LegacyForecastProductRedirect />
  },
  {
    path: routePaths.aiAdvisor,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="rag_assistant">
          <DashboardLayout>
            <RagAssistantPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.aiAdvisorChat,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="rag_assistant">
          <DashboardLayout>
            <RagAssistantPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.connectData,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="data_integration">
          <DashboardLayout>
            <ConnectDataPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.marketing,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="marketing_image_generation">
          <DashboardLayout>
            <MarketingStudioPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.reports,
    element: (
      <ProtectedRoute>
        <FeatureRouteGuard featureCodes="report_generation">
          <DashboardLayout>
            <UnifiedReportsCenterPage />
          </DashboardLayout>
        </FeatureRouteGuard>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.settings,
    element: (
      <ProtectedRoute>
        <DashboardLayout>
          <SettingsPage />
        </DashboardLayout>
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.settingsSecurity,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=security`} replace />
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.settingsTeam,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=team`} replace />
      </ProtectedRoute>
    )
  },
  {
    path: routePaths.settingsIntegrations,
    element: (
      <ProtectedRoute>
        <Navigate to={`${routePaths.settings}?tab=company`} replace />
      </ProtectedRoute>
    )
  },
  {
    path: "*",
    element: <Navigate to={routePaths.dashboard} replace />
  }
]);

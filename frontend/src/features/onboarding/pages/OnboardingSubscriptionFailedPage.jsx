import {useState} from 'react';
import {billingApi,getApiError} from '../../billing/api/customerBillingApi.js';
import { useOnboardingStore } from '../store/onboardingStore.js';
import { useNavigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';
import { SubscriptionResult } from '../../billing/components/SubscriptionResult.jsx';
import { OnboardingPageShell } from '../components/OnboardingPageShell.jsx';

export function OnboardingSubscriptionFailedPage() {
  const navigate = useNavigate();
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const reopen=async path=>{setBusy(true);setError('');try{await billingApi.cancelPendingCheckout();navigate(path);}catch(e){setError(getApiError(e).message);}finally{setBusy(false);}};
  const selected=useOnboardingStore(s=>s.selectedPlan),period=useOnboardingStore(s=>s.billingPeriod);
  return (
    <OnboardingPageShell wide showProgress={false}>
      <SubscriptionResult
        status="failed"
        primaryLoading={busy}
        actionError={error||null}
        onBack={() => reopen(routePaths.onboardingPlan)}
        onPrimary={() => reopen(selected==='custom'?routePaths.onboardingPlanCustom+'?returnTo='+encodeURIComponent(routePaths.onboardingPlan):routePaths.onboardingPlanPayment+'?'+new URLSearchParams({plan:selected||'',period:period||'monthly'}))}
      />
    </OnboardingPageShell>
  );
}

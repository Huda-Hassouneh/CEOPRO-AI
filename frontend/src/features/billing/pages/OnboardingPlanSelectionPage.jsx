import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { OriginalPlanSelector } from '../components/OriginalPlanSelector.jsx';
import { usePlans } from '../hooks/usePlans.js';
import { useSubscription } from '../hooks/useSubscription.js';
import { hasActivePlanAccess } from '../utils/onboardingRouting.js';
import { toOriginalPlan } from '../api/originalBillingModel.js';
import { useOnboardingStore, saveOnboardingPlan } from '../../onboarding/store/onboardingStore.js';
import { OnboardingPageShell } from '../../onboarding/components/OnboardingPageShell.jsx';
import { OnboardingActions } from '../../onboarding/components/OnboardingActions.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import '../styles/Billing.css';
import '../styles/PlansSubscription.css';
export function OnboardingPlanSelectionPage(){
 const {t}=useI18n(),navigate=useNavigate(),tenant=useAuthStore(s=>s.tenantId);
 const plansQuery=usePlans(),subscriptionQuery=useSubscription(tenant);
 const selected=useOnboardingStore(s=>s.selectedPlan)||'',period=useOnboardingStore(s=>s.billingPeriod)||'monthly';
 const setSelected=value=>useOnboardingStore.setState({selectedPlan:value}),setPeriod=value=>useOnboardingStore.setState({billingPeriod:value});
 const [busy,setBusy]=useState(false),[error,setError]=useState('');
 if(plansQuery.isPending||subscriptionQuery.isPending)return <Skeleton height="400px"/>;
 if(plansQuery.isError||subscriptionQuery.isError)return <EmptyState title={t('billing.management.errorTitle')} description={t('billing.management.errorDescription')} action={<Button onClick={()=>{plansQuery.refetch();subscriptionQuery.refetch();}}>{t('billing.management.retry')}</Button>}/>;
 const plans=plansQuery.data.plans.filter(p=>p.selfServe),chosen=plans.find(p=>p.id===selected);
 const selectable=selected==='custom'||Boolean(chosen&&chosen.prices?.[period]&&(subscriptionQuery.data.trialAvailable||plansQuery.data.paymentsEnabled&&chosen.prices[period].purchasable));
 const next=async(plan,term=period,destination)=>{
  setBusy(true);setError('');
  try{await saveOnboardingPlan(plan,term);navigate(destination||(plan==='custom'?routePaths.onboardingPlanCustom+'?returnTo='+encodeURIComponent(routePaths.onboardingPlan):routePaths.onboardingPlanPayment+'?'+new URLSearchParams({plan,period:term})));}
  catch{setError(t('onboarding.persistence.error'));}finally{setBusy(false);}
 };
 return <OnboardingPageShell step={5} title={t('billing.choose.title')} subtitle={t('billing.choose.subtitle')}>
 {error&&<p role="alert">{error}</p>}
 {!plansQuery.data.paymentsEnabled&&<p role="note">{t('billing.management.paymentsUnavailableHint')}</p>}
 <OriginalPlanSelector plans={plans.map(toOriginalPlan)} selectedPlan={selected} billingPeriod={period} onPlanSelect={setSelected} onPeriodChange={setPeriod} onBuildCustom={()=>setSelected('custom')} showCustomPlan/>
 <OnboardingActions onBack={()=>navigate(routePaths.onboardingObjectives)} onContinue={()=>next(selected)} disabled={!selectable} loading={busy}/>
 {hasActivePlanAccess(subscriptionQuery.data)&&<Button variant="ghost" disabled={busy} onClick={()=>next(subscriptionQuery.data.planId,subscriptionQuery.data.billingPeriod,routePaths.onboardingConnectData)}>{t(subscriptionQuery.data.billingStatus==='trialing'?'onboarding.persistence.currentTrial':'onboarding.common.continue')}</Button>}
 </OnboardingPageShell>;
}

import { useEffect } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { onboardingApi } from '../api/onboardingApi.js';
import { useOnboardingStore } from '../store/onboardingStore.js';
import { getOnboardingPathForStep } from '../config/onboardingSteps.js';
import { useAuthStore } from '../../auth/store/authStore.js';
import { RoutePending } from '../../../app/router/RoutePending.jsx';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import '../styles/Onboarding.css';
export function OnboardingGate({step,children}){
 const tenant=useAuthStore(s=>s.tenantId),hydrate=useOnboardingStore(s=>s.hydrate),location=useLocation(),{t}=useI18n();
 const query=useQuery({queryKey:['onboarding-state',tenant,location.pathname],queryFn:onboardingApi.getState,staleTime:0,refetchOnWindowFocus:false});
 useEffect(()=>{if(query.data && !query.isFetching)hydrate(query.data);},[query.data,query.isFetching,hydrate]);
 if(query.isPending || query.isFetching)return <RoutePending/>;
 if(query.isError)return <div role="alert">{t('onboarding.persistence.error')}<Button onClick={()=>query.refetch()}>{t('billing.management.retry')}</Button></div>;
 if(step && !query.data.isComplete && step>query.data.currentStep)return <Navigate to={getOnboardingPathForStep(query.data.currentStep)} replace/>;
 return children;
}
export function OnboardingResume(){
 const tenant=useAuthStore(s=>s.tenantId);
 const query=useQuery({queryKey:['onboarding-state',tenant],queryFn:onboardingApi.getState,staleTime:0,refetchOnWindowFocus:false});
 if(query.isPending || query.isFetching)return <RoutePending/>;
 if(query.isError)return <OnboardingGate/>;
 return <Navigate to={query.data.isComplete?'/dashboard':getOnboardingPathForStep(query.data.currentStep)} replace/>;
}

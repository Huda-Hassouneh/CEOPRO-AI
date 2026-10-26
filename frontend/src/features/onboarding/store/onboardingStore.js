import { create } from 'zustand';
import { onboardingApi } from '../api/onboardingApi.js';
// Server-backed and tenant scoped. No shared localStorage preview state or commercial defaults.
const initial={revision:0,highestCompletedStep:0,currentStep:1,country:'',city:'',industry:'',businessSize:'',annualRevenue:'',objectives:[],isComplete:false,busy:false,error:null,sourceStatuses:{},websiteUrl:''};
export const useOnboardingStore=create((set,get)=>({
  ...initial,
  setWebsiteUrl:websiteUrl=>set({websiteUrl}),
  setSourceStatus:(source,status,error='')=>set(s=>({sourceStatuses:{...s.sourceStatuses,[source]:{status,error}}})),
  hydrate:state=>set({...initial,...state}),
  setIndustry:industry=>set({industry}),
  setBusinessProfile:values=>set(values),
  setRegionalPreferences:values=>set(values),
  toggleObjective:objective=>set(s=>({objectives:s.objectives.includes(objective)?s.objectives.filter(i=>i!==objective):[...s.objectives,objective]})),
  completeStep:async step=>{
    if(get().busy)return false;
    const s=get(),keys={1:['country','city'],2:['industry'],3:['businessSize','annualRevenue'],4:['objectives']}[step];
    set({busy:true,error:null});
    try{
      const payload=Object.fromEntries(keys.map(k=>[k,s[k]]));
      if(step===1)payload.language=document.documentElement.lang==='ar'?'ar':'en';
      const saved=await onboardingApi.saveStep({...payload,step,expected_revision:s.revision});
      set({...saved,busy:false});return true;
    }catch(error){set({busy:false,error:error?.response?.data?.detail});return false;}
  },
}));
export async function saveOnboardingPlan(selectedPlan,billingPeriod='monthly'){
 const current=await onboardingApi.getState();
 if(current.isComplete)return current;
 return onboardingApi.saveStep({step:5,expected_revision:current.revision,selectedPlan,billingPeriod});
}

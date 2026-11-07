import { create } from 'zustand';
import { onboardingApi } from '../api/onboardingApi.js';
// Server-backed and tenant scoped. No shared localStorage preview state or commercial defaults.
const initial={revision:0,highestCompletedStep:0,currentStep:1,country:'',city:'',savedRegion:{},industry:'',businessSize:'',annualRevenue:'',objectives:[],isComplete:false,busy:false,error:null,sourceStatuses:{},websiteUrl:''};
let generation = 0;
export const useOnboardingStore=create((set,get)=>({
  ...initial,
  reset:()=>{generation++;set({...initial});},
  setWebsiteUrl:websiteUrl=>set({websiteUrl}),
  setSourceStatus:(source,status,error='')=>set(s=>({sourceStatuses:{...s.sourceStatuses,[source]:{status,error}}})),
  hydrate:state=>set({...initial,...state,savedRegion:{country:state.country,city:state.city}}),
  setIndustry:industry=>set({industry}),
  setBusinessProfile:values=>set(values),
  setRegionalPreferences:values=>set(s=>({...values,...(values.country!==undefined && values.country!==s.country ? {city:''} : {})})),
  toggleObjective:objective=>set(s=>({objectives:s.objectives.includes(objective)?s.objectives.filter(i=>i!==objective):[...s.objectives,objective]})),
  completeStep:async step=>{
    if(get().busy)return false;
    const started=generation;
    const s=get(),keys={1:['country','city'],2:['industry'],3:['businessSize','annualRevenue'],4:['objectives']}[step];
    set({busy:true,error:null});
    try{
      const payload=Object.fromEntries(keys.map(k=>[k,s[k]]));
      if(step===1)payload.language=document.documentElement.lang==='ar'?'ar':'en';
      const saved=await onboardingApi.saveStep({...payload,step,expected_revision:s.revision});
      if(started!==generation)return false;
      set({...saved,savedRegion:{country:saved.country,city:saved.city},busy:false});return true;
    }catch(error){if(started===generation)set({busy:false,error:error?.response?.data?.detail});return false;}
  },
}));
export async function saveOnboardingPlan(selectedPlan,billingPeriod='monthly'){
 const started=generation;
 const current=await onboardingApi.getState();
 if(started!==generation)throw new Error('Account changed during plan selection.');
 if(current.isComplete)return current;
 const saved=await onboardingApi.saveStep({step:5,expected_revision:current.revision,selectedPlan,billingPeriod});
 if(started!==generation)throw new Error('Account changed during plan selection.');
 return saved;
}

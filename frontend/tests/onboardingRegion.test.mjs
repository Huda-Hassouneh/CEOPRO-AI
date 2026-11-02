import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { COUNTRY_CODES, countryOptions } from '../src/shared/config/countries.js';
import { cityOptions, filterCityOptions } from '../src/features/onboarding/config/locationOptions.js';
import { LEGACY_COUNTRY_CITIES } from '../src/features/onboarding/config/countries.js';
import { useOnboardingStore } from '../src/features/onboarding/store/onboardingStore.js';
import httpClient from '../src/shared/lib/httpClient.js';

const read = country => JSON.parse(readFileSync(new URL(`../src/shared/config/locations/${country}.json`, import.meta.url)));
const cities = country => cityOptions(country,read(country),'en',key=>key);
const cases = [['JO','amman'],['US','new-york-city'],['DE','berlin'],['JP','tokyo'],['BR','sao-paulo'],['ZA','johannesburg'],['AU','sydney']];

test('shared production country source has all 249 current ISO codes, localized and sorted',()=>{
  assert.equal(COUNTRY_CODES.length,249);assert.equal(new Set(COUNTRY_CODES).size,249);
  for(const [country] of cases)assert.ok(COUNTRY_CODES.includes(country));
  for(const locale of ['en','ar']){
    const options=countryOptions(locale),collator=new Intl.Collator(locale);
    assert.ok(options.every((o,i)=>!i||collator.compare(options[i-1].label,o.label)<=0));
    assert.notEqual(options.find(o=>o.value==='JO').label,'JO');
  }
});

test('representative cities are selectable from country-specific broad catalogs',()=>{
  for(const [country,city] of cases){
    const options=cities(country);assert.ok(options.some(o=>o.value===city),`${country}/${city}`);
    const label=options.find(o=>o.value===city).label;
    assert.ok(filterCityOptions(options,label, '').some(o=>o.value===city));
  }
  assert.ok(read('US').length>10000);assert.ok(read('DE').length>1000);
  assert.ok(!cities('DE').some(o=>o.value==='amman'));
});

test('historical translated values and saved strings are readable only for their saved country',()=>{
  for(const [country,legacy] of Object.entries(LEGACY_COUNTRY_CITIES)){
    for(const item of legacy)assert.ok(cities(country).some(o=>o.value===item.value));
  }
  const saved={country:'JO',city:'Amman (historic spelling)'};
  assert.ok(cityOptions('JO',read('JO'),'ar',key=>key,saved).some(o=>o.value===saved.city));
  assert.ok(!cityOptions('DE',read('DE'),'ar',key=>key,saved).some(o=>o.value===saved.city));
});

test('country changes clear city and valid ISO/slug payload survives submission and rehydration',async()=>{
  const adapter=httpClient.defaults.adapter;
  globalThis.document={documentElement:{lang:'en'}};
  try{
    useOnboardingStore.getState().hydrate({country:'JO',city:'amman',revision:0});
    useOnboardingStore.getState().setRegionalPreferences({country:'DE',city:'amman'});
    assert.equal(useOnboardingStore.getState().city,'');
    useOnboardingStore.getState().setRegionalPreferences({city:'berlin'});
    let request;
    httpClient.defaults.adapter=async config=>{
      request=JSON.parse(config.data);
      return {data:{...request,revision:1,currentStep:2,highestCompletedStep:1},status:200,statusText:'OK',headers:{},config};
    };
    assert.equal(await useOnboardingStore.getState().completeStep(1),true);
    assert.deepEqual(request,{country:'DE',city:'berlin',language:'en',step:1,expected_revision:0});
    const saved=useOnboardingStore.getState();
    useOnboardingStore.getState().reset();useOnboardingStore.getState().hydrate(saved);
    assert.equal(useOnboardingStore.getState().country,'DE');assert.equal(useOnboardingStore.getState().city,'berlin');
  }finally{httpClient.defaults.adapter=adapter;delete globalThis.document;useOnboardingStore.getState().reset();}
});

import test from 'node:test';
import assert from 'node:assert/strict';
import { QueryObserver } from '@tanstack/react-query';
import { useAuthStore } from '../src/features/auth/store/authStore.js';
import { queryClient } from '../src/shared/lib/queryClient.js';
import { useOnboardingStore } from '../src/features/onboarding/store/onboardingStore.js';
import httpClient, { configureHttpClientAuth } from '../src/shared/lib/httpClient.js';
import { saveOnboardingPlan } from '../src/features/onboarding/store/onboardingStore.js';
import { savePendingRegistration, readPendingRegistration } from '../src/features/auth/pendingRegistration.js';
const session = (user, tenant = user) => ({ user: { id: user }, tenantId: tenant, accessToken: `invalid-fixture-${user}-${tenant}` });
const storage = () => { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key,value) => data.set(key,value), removeItem: key => data.delete(key) }; };
const prepare = () => {
  globalThis.window = { localStorage: storage() }; globalThis.sessionStorage = storage();
  useAuthStore.getState().clearSession(); useAuthStore.getState().setSession(session('A'));
  queryClient.setQueryData(['settings-company', 'gate'], { company: { onboardingCompletedAt: '2026-01-01' } });
  queryClient.setQueryData(['subscription','A'], { assigned: true, planId: 'growth' });
  useOnboardingStore.getState().hydrate({ isComplete: true, highestCompletedStep: 6 });
};
const clean = () => { useAuthStore.getState().clearSession(); delete globalThis.window; delete globalThis.sessionStorage; };

test('logout clears authentication, all account queries, onboarding and transient setup state', () => {
  prepare();
  savePendingRegistration({ email: 'fixture@example.test', registration_token: 'invalid-fixture-only' });
  sessionStorage.setItem('keel.onboarding.returnPath','/market'); sessionStorage.setItem('keel.onboarding.checkoutPending','1');
  window.localStorage.setItem('theme','dark');
  useAuthStore.getState().clearSession();
  assert.equal(useAuthStore.getState().tenantId,null);assert.equal(window.localStorage.getItem('ceopro_auth_session'),null);
  assert.equal(queryClient.getQueryCache().getAll().length,0);assert.equal(useOnboardingStore.getState().isComplete,false);
  assert.equal(readPendingRegistration(),null);assert.equal(sessionStorage.getItem('keel.onboarding.returnPath'),null);
  assert.equal(sessionStorage.getItem('keel.onboarding.checkoutPending'),null);assert.equal(window.localStorage.getItem('theme'),'dark');clean();
});

test('B cannot read A cache on direct login, cross-tab adoption, expiry or workspace switch', () => {
  for (const transition of [() => useAuthStore.getState().setSession(session('B')), () => useAuthStore.getState().adoptSession(session('B')), () => useAuthStore.getState().expireSession(), () => useAuthStore.getState().setSession(session('A','other'))]) {
    prepare();transition();assert.equal(queryClient.getQueryCache().getAll().length,0);assert.equal(useOnboardingStore.getState().highestCompletedStep,0);
  }clean();
});

test('same-identity token renewal preserves current data; delayed A refresh cannot overwrite B', () => {
  prepare();const old=useAuthStore.getState().accessToken;
  useAuthStore.getState().setAccessToken('invalid-refreshed-A',old);assert.ok(queryClient.getQueryData(['subscription','A']));
  useAuthStore.getState().adoptSession({...session('A'),accessToken:'invalid-tab-refresh-A'});assert.ok(queryClient.getQueryData(['subscription','A']));
  useAuthStore.getState().setSession(session('B'));useAuthStore.getState().setAccessToken('invalid-late-A',old);
  assert.equal(useAuthStore.getState().accessToken,session('B').accessToken);clean();
});

test('an in-flight A query finishing after logout cannot repopulate B cache', async () => {
  prepare();let finish;const old=queryClient.fetchQuery({queryKey:['private-late'],queryFn:()=>new Promise(resolve=>{finish=resolve;})}).catch(()=>{});
  useAuthStore.getState().clearSession();useAuthStore.getState().setSession(session('B'));finish({private:'A'});await old;
  assert.equal(queryClient.getQueryData(['private-late']),undefined);clean();
});

test('an in-flight A onboarding save cannot hydrate B after an identity change', async () => {
  prepare();const original=httpClient.defaults.adapter;let finish;
  globalThis.document={documentElement:{lang:'en'}};
  httpClient.defaults.adapter=config=>new Promise(resolve=>{finish=data=>resolve({data,status:200,statusText:'OK',headers:{},config});});
  try {
    const saved=useOnboardingStore.getState().completeStep(1);await new Promise(resolve=>setTimeout(resolve,0));useAuthStore.getState().setSession(session('B'));
    finish({isComplete:true,currentStep:6});assert.equal(await saved,false);assert.equal(useOnboardingStore.getState().isComplete,false);
  }finally{httpClient.defaults.adapter=original;delete globalThis.document;clean();}
});

test('B company guard fetches independently while A company is still fresh', async () => {
  prepare();useAuthStore.getState().setSession(session('B'));let calls=0;
  const observer=new QueryObserver(queryClient,{queryKey:['settings-company','B','B','gate'],queryFn:async()=>{calls++;return{company:{onboardingCompletedAt:null}};},staleTime:300000});
  const stop=observer.subscribe(()=>{});await new Promise(resolve=>setTimeout(resolve,10));
  assert.equal(calls,1);assert.equal(observer.getCurrentResult().data.company.onboardingCompletedAt,null);stop();clean();
});


test('requests bind the initiating identity before an asynchronous account switch', async () => {
  prepare();const original=httpClient.defaults.adapter;const seen=[];
  configureHttpClientAuth({getAccessToken:()=>useAuthStore.getState().accessToken});
  httpClient.defaults.adapter=async config=>{seen.push(config.headers.Authorization);return{data:{},status:200,statusText:'OK',headers:{},config};};
  try {
    const pending=httpClient.get('/synthetic-identity-check');useAuthStore.getState().setSession(session('B'));await pending;
    assert.deepEqual(seen,[`Bearer ${session('A').accessToken}`]);
  }finally{httpClient.defaults.adapter=original;configureHttpClientAuth({});clean();}
});

test('an A plan-state response cannot submit a plan selection using B credentials', async () => {
  prepare();const original=httpClient.defaults.adapter;let finish;let posts=0;
  httpClient.defaults.adapter=config=>{if(config.method==='post'||config.method==='put')posts++;return new Promise(resolve=>{finish=data=>resolve({data,status:200,statusText:'OK',headers:{},config});});};
  try {
    const pending=saveOnboardingPlan('growth');useAuthStore.getState().setSession(session('B'));
    finish({revision:4,isComplete:false});await assert.rejects(pending,/Account changed/);assert.equal(posts,0);
  }finally{httpClient.defaults.adapter=original;clean();}
});

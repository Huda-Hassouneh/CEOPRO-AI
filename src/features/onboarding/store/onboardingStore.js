import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import { DEFAULT_CUSTOM_PLAN, getPreviewPlan } from '../../billing/config/billingPreviewData.js';

const migrateCustomPlan = (customPlan = {}) => {
  const { imageGenerations, ...currentValues } = customPlan;
  return {
    ...DEFAULT_CUSTOM_PLAN,
    ...currentValues,
    reports: customPlan.reports ?? imageGenerations ?? DEFAULT_CUSTOM_PLAN.reports,
  };
};

const initialState = {
  currentStep: 1,
  highestCompletedStep: 0,
  industry: '',
  businessSize: '',
  annualRevenue: '1m-10m',
  country: 'JO',
  city: 'amman',
  objectives: [],
  selectedPlan: '',
  checkoutMode: 'trial',
  standardRecommendationResolved: false,
  billingPeriod: 'monthly',
  customPlan: { ...DEFAULT_CUSTOM_PLAN },
  step5Completed: false,
  sourceStatuses: {
    analytics: { status: 'not-connected', error: '' },
    website: { status: 'not-connected', error: '' },
    database: { status: 'not-connected', error: '' },
    documents: { status: 'not-connected', error: '' },
  },
  websiteUrl: '',
  databaseProvider: '',
  downloadedTemplates: [],
  isComplete: false,
};

export const useOnboardingStore = create(persist((set) => ({
  ...initialState,
  setCurrentStep: (currentStep) => set({ currentStep }),
  completeStep: (step) => set((state) => ({
    currentStep: Math.min(6, step + 1),
    highestCompletedStep: Math.max(state.highestCompletedStep, step),
  })),
  setIndustry: (industry) => set({ industry }),
  setBusinessProfile: ({ businessSize, annualRevenue }) => set({ businessSize, annualRevenue }),
  setRegionalPreferences: ({ country, city }) => set((state) => ({
    country: country ?? state.country,
    city: city ?? state.city,
  })),
  toggleObjective: (objective) => set((state) => ({
    objectives: state.objectives.includes(objective)
      ? state.objectives.filter((item) => item !== objective)
      : [...state.objectives, objective],
  })),
  setBillingPeriod: (billingPeriod) => set({ billingPeriod }),
  selectPlan: (selectedPlan) => set({ selectedPlan }),
    setPlanChoice: (selectedPlan, checkoutMode) => set({ selectedPlan, checkoutMode: getPreviewPlan(selectedPlan).trialDays > 0 ? checkoutMode : 'paid' }),
  resolveStandardRecommendation: () => set({ standardRecommendationResolved: true }),
  updateCustomPlan: (key, value) => set((state) => ({
    customPlan: { ...state.customPlan, [key]: value },
  })),
  completePlanStep: () => set((state) => ({
    step5Completed: true,
    currentStep: 6,
    highestCompletedStep: Math.max(state.highestCompletedStep, 5),
  })),
  setSourceStatus: (source, status, error = '') => set((state) => ({
    sourceStatuses: {
      ...state.sourceStatuses,
      [source]: { status, error },
    },
  })),
  setWebsiteUrl: (websiteUrl) => set({ websiteUrl }),
  setDatabaseProvider: (databaseProvider) => set({ databaseProvider }),
  markTemplateDownloaded: (templateId) => set((state) => ({
    downloadedTemplates: state.downloadedTemplates.includes(templateId)
      ? state.downloadedTemplates
      : [...state.downloadedTemplates, templateId],
  })),
  completeSetup: () => set({ isComplete: true, currentStep: 6, highestCompletedStep: 6 }),
  resetOnboarding: () => set({ ...initialState, customPlan: { ...DEFAULT_CUSTOM_PLAN } }),
}), {
  name: 'ceopro_onboarding_preview',
  version: 5,
  migrate: (persistedState, version) => ({
    ...persistedState,
    ...(version === 1 ? { currentStep: 1, highestCompletedStep: 0, step5Completed: false, isComplete: false } : {}),
    city: persistedState.city || '',
    customPlan: migrateCustomPlan(persistedState.customPlan),
    downloadedTemplates: persistedState.downloadedTemplates || [],
    sourceStatuses: version < 5
      ? {
        ...persistedState.sourceStatuses,
        documents: { status: 'not-connected', error: '' },
      }
      : persistedState.sourceStatuses,
  }),
  partialize: (state) => ({
    currentStep: state.currentStep,
    highestCompletedStep: state.highestCompletedStep,
    industry: state.industry,
    businessSize: state.businessSize,
    annualRevenue: state.annualRevenue,
    country: state.country,
    city: state.city,
    objectives: state.objectives,
    selectedPlan: state.selectedPlan,
    checkoutMode: state.checkoutMode,
    standardRecommendationResolved: state.standardRecommendationResolved,
    billingPeriod: state.billingPeriod,
    customPlan: state.customPlan,
    step5Completed: state.step5Completed,
    sourceStatuses: state.sourceStatuses,
    websiteUrl: state.websiteUrl,
    databaseProvider: state.databaseProvider,
    downloadedTemplates: state.downloadedTemplates,
    isComplete: state.isComplete,
  }),
}));

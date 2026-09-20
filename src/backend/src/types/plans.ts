export interface BillingOptionType {
  period: string;
  months: number;
  discountPercent: number;
  stripePriceId?: string;
}

export interface PlanFeatureInputDto {
  featureId: string;
  limitValue?: number | null; // null means unlimited
}

export interface CreatePlanDto {
  name: string;
  description?: string;
  price: number;
  currency?: string;
  billingIntervalValue: number;
  billingIntervalUnit: string;
  trialPeriodValue?: number;
  paymentProviderProductId?: string;
  paymentProviderPlanId?: string;
  isActive?: boolean; // Defaults to true
  billingOptions?: BillingOptionType[]; // Dynamic discount tabs
  features?: PlanFeatureInputDto[]; // Linked features and limits
}

export interface UpdatePlanDto extends Partial<CreatePlanDto> {}

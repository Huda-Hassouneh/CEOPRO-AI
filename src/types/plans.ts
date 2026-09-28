export interface BillingOptionType {
  period: string;
  months: number;
  discountPercent: number;
  stripePriceId?: string;
}

// Standard plans support true day/month/year recurrence. Custom plan quotes
// still use the existing month-based BillingOptionType contract.
export interface PlanBillingOptionType extends Omit<BillingOptionType, "months"> {
  months?: number;
  intervalUnit?: "day" | "month" | "year";
  intervalCount?: number;
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

export interface PayPalProduct {
  id: string;
  name: string;
  description: string;
  type: string;
  category: string;
}

export interface PayPalBillingPlan {
  id: string;
  product_id: string;
  name: string;
  description: string;
  status: string;
}

export interface PayPalTrialConfig {
  interval_unit: string;
  interval_count: number;
  price: 0;
  currency_code: string;
  total_cycles: number;
}

export interface PayPalRegularConfig {
  interval_unit: string;
  interval_count: number;
  price: number;
  currency_code: string;
  total_cycles: 0;
}

export interface PayPalPlanDetails {
  name: string;
  description: string;
  trialConfig?: PayPalTrialConfig | null;
  regularConfig: PayPalRegularConfig;
}

export interface PayPalService {
  generateAccessToken(): Promise<string>;

  createCatalog(
    accessToken: string,
    payload?: {
      name: string;
      description: string;
      type: string;
      category: string;
    }
  ): Promise<PayPalProduct>;

  createPlan(
    accessToken: string,
    productId: string,
    planDetails: PayPalPlanDetails
  ): Promise<PayPalBillingPlan>;

  paypalOnBoarding(): Promise<PayPalProduct>;
}

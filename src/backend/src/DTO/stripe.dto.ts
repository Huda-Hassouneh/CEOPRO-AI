export interface CustomerWithClockParams {
  email: string;
  name: string;
  testClockId: string;
  paymentMethodId?: string;
}

export interface SimulationParams {
  priceId: string;
  customerEmail: string;
  customerName?: string;
  advanceDays?: number;
  paymentMethodId?: string;
}

export interface SimulationResult {
  testClockId: string;
  customerId: string;
  subscriptionId: string;
  advancedTo: number;
}

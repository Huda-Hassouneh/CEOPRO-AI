import type {PricingServiceErrorCode} from '../types/pricing.types.js';
export class PricingRequestError extends Error {
  constructor(public code:PricingServiceErrorCode,message=code as string){super(message);this.name='PricingServiceError';}
}

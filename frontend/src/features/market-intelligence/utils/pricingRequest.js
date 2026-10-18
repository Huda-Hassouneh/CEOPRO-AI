export function pricingRequestRetryable(error){
  const backend=error?.response?.data?.error,reason=backend?.details?.reason;
  if(reason==='REQUEST_PENDING')return true;
  if(['INVALID_AI_RESULT','SOURCE_CHANGED','REQUEST_FAILED','REQUEST_EXPIRED','REQUEST_CONFLICT'].includes(reason))return false;
  return !error?.response || error.response.status>=500;
}
export function newPricingRequestId(){return globalThis.crypto.randomUUID();}

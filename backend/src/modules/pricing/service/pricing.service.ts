import {randomUUID} from 'node:crypto';
import {z} from 'zod';
import {getFeatureAccessInfo,FeatureUsageUnavailableError} from '../../features/repo/usage.repo.js';
import {readPricingExplanation,requestPricingRecommendation} from '../client/pricing.client.js';
import {getEligibleMarketPrices,getExchangeRates,getProductPricingContext} from '../repo/pricing.repo.js';
import {beginPricingRequest,failPricingRequest,finishPricingRequest,lookupPricingRequest,pricingHistory,recoverPricingRequests} from '../repo/pricing-request.repo.js';
import {PricingRequestError} from './pricing.errors.js';
import {comparablePrices,enforcePriceGuardrails,FX_FRESHNESS_DAYS,MARKET_FRESHNESS_DAYS,MAX_CHANGE_PCT,MIN_COST_MARKUP_PCT,summarizeMarket,validProduct,localMarketTarget} from './pricing.policy.js';
import type {PricingRecommendationResult,PricingServiceError} from '../types/pricing.types.js';

type Input={tenantId:string;userId:string;productId:string;requestId?:string};
export function isPricingServiceError(error:unknown):error is PricingServiceError {
  return error instanceof Error&&error.name==='PricingServiceError';
}
async function authorizedProduct(input:Input){
  if(!z.uuid().safeParse(input.productId).success||!z.uuid().safeParse(input.tenantId).success||!z.uuid().safeParse(input.userId).success)
    throw new PricingRequestError('INVALID_REQUEST');
  const access=await getFeatureAccessInfo(input.tenantId,'ai_pricing');
  if(!access.subscription||!access.planFeature)throw new FeatureUsageUnavailableError();
  const product=await getProductPricingContext(input.tenantId,input.userId,input.productId);
  if(!product)throw new PricingRequestError('PRODUCT_NOT_FOUND');
  return product;
}
export async function getPricingRecommendation(input:Input):Promise<PricingRecommendationResult>{
  const requestId=input.requestId??randomUUID();
  if(!z.uuid().safeParse(requestId).success)throw new PricingRequestError('INVALID_REQUEST');
  const product=await authorizedProduct(input);
  await recoverPricingRequests(input);
  const cached=await lookupPricingRequest(input,requestId,input.productId);
  if(cached)return cached; // Replay never calls AI or spends another allowance.
  if(!validProduct(product))throw new PricingRequestError('INVALID_PRODUCT_PRICE');
  const started=await beginPricingRequest(input,requestId,input.productId);
  if(started.cached)return started.cached;
  try {
    const now=new Date();
    const points=await getEligibleMarketPrices({...input,observedBefore:now,observedAfter:new Date(now.getTime()-MARKET_FRESHNESS_DAYS*86400000)});
    const rates=await getExchangeRates({fromCurrencies:points.map(p=>p.currency),toCurrency:product.currency});
    const checkedPrices=comparablePrices(points,rates,product.currency,now);
    // Currency conversion alone is insufficient to establish a comparable
    // local market. Preserve the AI policy: cross-currency rows are reference
    // only and cannot determine the average, action or sample confidence.
    const sources=checkedPrices.filter(p=>p.original_currency===product.currency);
    const references=checkedPrices.filter(p=>p.original_currency!==product.currency);
    const market=summarizeMarket(sources.map(p=>p.converted_price));
    // Node and AI use the same local-currency sample and the same verified
    // exchange rates for separately labelled cross-currency reference only.
    const ai=sources.length?await requestPricingRecommendation({product:{product_name:product.productName,
      current_price:product.currentPrice,currency:product.currency,cost_price:product.costPrice},
      competitorPrices:checkedPrices.map(s=>({competitor_name:s.competitor_name,price:s.original_price,currency:s.original_currency,
        observed_at:s.observed_at})),exchangeRates:references.length?references.map(s=>({from_currency:s.original_currency,
          to_currency:product.currency,rate:s.conversion!.rate,as_of:s.conversion!.as_of,source:s.conversion!.source})):null}):null;
    let status:'OK'|'UNKNOWN'='UNKNOWN',action:PricingRecommendationResult['action']=null,suggestion:number|null=null,
      confidence:number|null=null,clamped:boolean|null=null,marginClamped:boolean|null=null,floor:number|null=null,override=false;
    let reason:string|null=!sources.length?(references.length?'CROSS_CURRENCY_ONLY':points.length?'NO_VERIFIED_FX':'NO_COMPARABLE_PRICES'):'AI_UNKNOWN';
    if(ai?.result.status==='OK'){
      const result=ai.result;
      if(Math.abs(result.current_price-product.currentPrice)>1e-7||result.matched_competitor_count!==sources.length||result.suggested_price<=0)
        throw new PricingRequestError('INVALID_AI_RESULT');
      let guarded;
      // The established rule is a 5% competitiveness band around the local
      // market mean. Recompute it independently before applying both limits;
      // even an in-range provider suggestion cannot change that policy.
      try{guarded=enforcePriceGuardrails(product,localMarketTarget(product.currentPrice,market.average!));}catch{throw new PricingRequestError('INVALID_AI_RESULT');}
      status='OK';reason=null;action=guarded.action;suggestion=guarded.suggestedPrice;confidence=result.confidence_score;
      clamped=guarded.guardrailClamped;
      marginClamped=guarded.marginClamped;
      floor=guarded.floor;override=guarded.movementCapOverridden;
    }
    const explanation=(locale:'en'|'ar')=>{
      const ar=locale==='ar',fmt=(n:number|null)=>n===null?'—':new Intl.NumberFormat(locale,{maximumFractionDigits:4}).format(n);
      if(status==='UNKNOWN') {
        if(reason==='CROSS_CURRENCY_ONLY')return ar?'تتوفر أسعار بعملات أخرى للمرجع فقط، لكنها لا تكفي وحدها لإنشاء توصية تسعير محلية. لم تُحتسب توصية.':'Only cross-currency reference prices are available. Currency conversion alone cannot establish a local pricing recommendation. No recommendation credit was charged.';
        if(reason==='NO_VERIFIED_FX')return ar?'لا تتوفر أسعار منافسين قابلة للمقارنة بعد التحقق من حداثة أسعار الصرف. لم تُحتسب توصية.':'No comparable competitor prices remain after verifying currency conversion rates. No recommendation credit was charged.';
        if(reason==='NO_COMPARABLE_PRICES')return ar?'لا توجد أسعار حديثة ومؤكدة لمنافسين متابَعين ومنتجات متطابقة مؤكدة. لم تُحتسب توصية.':'No recent, verified prices from tracked competitors with confirmed product matches are available. No recommendation credit was charged.';
        return ar?'لم تُنتج خدمة التسعير توصية قابلة للاستخدام. لم تُحتسب توصية.':'The pricing service could not produce a usable recommendation. No recommendation credit was charged.';
      }
      const verb=ar?{raise:'رفع السعر إلى',lower:'خفض السعر إلى',hold:'الإبقاء على السعر عند'}[action!]:{raise:'Raise the price to',lower:'Lower the price to',hold:'Hold the price at'}[action!];
      let text=ar?`${verb} ${fmt(suggestion)} ${product.currency}. استنادًا إلى ${sources.length} منافسًا بمتوسط سعر ${fmt(market.average)} ${product.currency}.`:
        `${verb} ${fmt(suggestion)} ${product.currency}. Based on ${sources.length} competitors averaging ${fmt(market.average)} ${product.currency}.`;
      text+=ar?' حد تغيير السعر 15٪، مع أولوية الحد الأدنى البالغ 10٪ فوق التكلفة عند توفرها.':' The movement limit is 15%; the minimum of 10% above cost takes priority when cost is known.';
      if(override)text+=ar?' تجاوز الحد الأدنى فوق التكلفة سقف الزيادة البالغ 15٪.':' The cost floor overrides the 15% increase cap.';
      if(product.costPrice===null)text+=ar?' التكلفة غير متوفرة، لذلك لم يُطبّق حد أدنى فوق التكلفة.':' Cost is unknown, so no cost floor was applied.';
      return text;
    };
    const explanationI18n={en:explanation('en'),ar:explanation('ar')};
    return await finishPricingRequest(input,requestId,product,{status,action,current_price:product.currentPrice,suggested_price:suggestion,
      market_min:market.min,market_max:market.max,market_avg:market.average,market_median:market.median,
      matched_competitor_count:sources.length,confidence_score:confidence,guardrail_clamped:clamped,margin_guardrail_clamped:marginClamped,
      clamped,max_change_pct:MAX_CHANGE_PCT,min_margin_pct:product.costPrice===null?null:MIN_COST_MARKUP_PCT,floor_price:floor,
      explanation:explanationI18n.en,explanation_i18n:explanationI18n,request_id:requestId,generated_at:now.toISOString(),
      sources,reference_sources:references,market_as_of:now.toISOString(),oldest_observation_at:sources.length?sources.reduce((old,s)=>s.observed_at<old?s.observed_at:old,sources[0]!.observed_at):null,
      market_freshness_days:MARKET_FRESHNESS_DAYS,fx_freshness_days:FX_FRESHNESS_DAYS,reason,charged:status==='OK',
      currency:product.currency,product_version:product.version,product_cost_price:product.costPrice,guardrail_precedence:'cost_floor',
      movement_cap_overridden:override,
      provider_suggested_price:ai?.result.status==='OK'?ai.result.suggested_price:null,
      provider_adjusted:ai?.result.status==='OK'?(Math.abs(ai.result.suggested_price-suggestion!)>1e-7||ai.result.action!==action):false,
      provider_explanation:ai?readPricingExplanation(ai):null});
  }catch(error){
    await failPricingRequest(input,requestId,isPricingServiceError(error)?error.code:'GENERATION_FAILED');
    throw error;
  }
}
export async function getPricingHistory(input:Input){
  const product=await authorizedProduct(input);
  const history=await pricingHistory(input,input.productId);
  if(!history.length)return {recommendations:[]};
  const now=Date.now();
  const currentPoints=await getEligibleMarketPrices({...input,observedBefore:new Date(now),observedAfter:new Date(now-MARKET_FRESHNESS_DAYS*86400000)});
  const currentRates=await getExchangeRates({fromCurrencies:currentPoints.map(p=>p.currency),toCurrency:product.currency});
  const currentSources=comparablePrices(currentPoints,currentRates,product.currency,new Date(now));
  const signature=(sources:typeof currentSources)=>JSON.stringify(sources.map(s=>[s.competitor_price_id,s.original_price,s.original_currency,s.observed_at,s.conversion])
    .sort((a,b)=>String(a[0]).localeCompare(String(b[0]))));
  const currentSignature=signature(currentSources);
  return {recommendations:history.map(r=>({...r,is_stale:r.product_version!==product.version||r.current_price!==product.currentPrice||
    r.product_cost_price!==product.costPrice||r.currency!==product.currency||
    signature([...r.sources,...r.reference_sources])!==currentSignature||
    (r.oldest_observation_at!==null&&now-Date.parse(r.oldest_observation_at)>MARKET_FRESHNESS_DAYS*86400000)||
    r.reference_sources.some(s=>s.conversion!==null&&now-Date.parse(s.conversion.as_of)>FX_FRESHNESS_DAYS*86400000)}))};
}

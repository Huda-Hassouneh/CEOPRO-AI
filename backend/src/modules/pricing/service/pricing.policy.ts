import {Prisma} from '../../../generated/prisma/client.js';
import type {MarketPricePoint,PricingRate,PricingSource,MarketPriceStats,PricingProductContext} from '../types/pricing.types.js';

export const MARKET_FRESHNESS_DAYS=30;
export const FX_FRESHNESS_DAYS=7;
export const MAX_CHANGE_PCT=0.15;
// This is a markup on cost, not a gross-margin percentage of selling price.
export const MIN_COST_MARKUP_PCT=0.10;
export const COMPETITIVENESS_THRESHOLD_PCT=0.05;
const DAY_MS=86400000;
const D=(n:number)=>new Prisma.Decimal(n);
export function currencyDigits(currency:string):number {
  if(['BHD','IQD','JOD','KWD','LYD','OMR','TND'].includes(currency))return 3;
  if(['BIF','CLP','DJF','GNF','ISK','JPY','KMF','KRW','PYG','RWF','UGX','UYI','VND','VUV','XAF','XOF','XPF'].includes(currency))return 0;
  return 2;
}
export function roundMoney(value:number,currency:string):number {
  return D(value).toDecimalPlaces(currencyDigits(currency),Prisma.Decimal.ROUND_HALF_UP).toNumber();
}
export function freshDate(value:Date,now:Date,days:number):boolean {
  const time=value.getTime();return Number.isFinite(time)&&time<=now.getTime()&&time>=now.getTime()-days*DAY_MS;
}
export function validProduct(product:PricingProductContext):boolean {
  return Number.isFinite(product.currentPrice)&&product.currentPrice>0&&/^[A-Z]{3}$/.test(product.currency)&&
    (product.costPrice===null||(Number.isFinite(product.costPrice)&&product.costPrice>=0));
}
export function comparablePrices(points:MarketPricePoint[],rates:PricingRate[],currency:string,now:Date):PricingSource[] {
  const seen=new Set<string>(),result:PricingSource[]=[];
  for(const point of [...points].sort((a,b)=>b.observedAt.getTime()-a.observedAt.getTime()||b.competitorPriceId.localeCompare(a.competitorPriceId))) {
    if(seen.has(point.competitorId))continue;
    // Reserve the competitor slot before validation: never revive older data
    // behind an invalid latest observation (repository also checks flags).
    seen.add(point.competitorId);
    if(!Number.isFinite(point.price)||point.price<=0||!freshDate(point.observedAt,now,MARKET_FRESHNESS_DAYS))continue;
    let price=point.price,conversion:PricingSource['conversion']=null;
    if(point.currency!==currency) {
      const rate=rates.find(r=>r.fromCurrency===point.currency&&r.toCurrency===currency&&
        Number.isFinite(r.rate)&&r.rate>0&&freshDate(r.asOf,now,FX_FRESHNESS_DAYS)&&r.source.trim()&&r.source!=='unspecified');
      if(!rate)continue;
      price=D(point.price).mul(rate.rate).toNumber();
      conversion={rate:rate.rate,as_of:rate.asOf.toISOString(),source:rate.source};
    }
    if(!Number.isFinite(price)||price<=0)continue;
    price=roundMoney(price,currency);if(price<=0)continue;
    result.push({competitor_price_id:point.competitorPriceId,mapping_id:point.mappingId,competitor_id:point.competitorId,
      competitor_name:point.competitorName,original_price:point.price,original_currency:point.currency,
      converted_price:price,currency,observed_at:point.observedAt.toISOString(),conversion});
  }
  return result;
}
export function summarizeMarket(prices:number[]):MarketPriceStats {
  const sorted=prices.filter(n=>Number.isFinite(n)&&n>0).sort((a,b)=>a-b),n=sorted.length;
  if(!n)return {min:null,max:null,average:null,median:null,count:0};
  const sum=sorted.reduce((s,n)=>s.add(n),D(0));
  return {min:sorted[0]!,max:sorted[n-1]!,average:sum.div(n).toNumber(),
    median:n%2?sorted[Math.floor(n/2)]!:D(sorted[n/2-1]!).add(sorted[n/2]!).div(2).toNumber(),count:n};
}
export function enforcePriceGuardrails(product:PricingProductContext,suggestion:number) {
  if(!Number.isFinite(suggestion)||suggestion<=0)throw new Error('Invalid pricing suggestion.');
  const digits=currencyDigits(product.currency),current=D(product.currentPrice);
  // Round inward so currency rounding cannot exceed the movement bounds.
  const lower=current.mul(1-MAX_CHANGE_PCT).toDecimalPlaces(digits,Prisma.Decimal.ROUND_CEIL);
  const upper=current.mul(1+MAX_CHANGE_PCT).toDecimalPlaces(digits,Prisma.Decimal.ROUND_FLOOR);
  // A price below one currency unit can leave no representable point inside
  // the band. It cannot yield a usable recommendation.
  if(lower.gt(upper))throw new Error('No representable price within movement bounds.');
  const rounded=D(suggestion).toDecimalPlaces(digits,Prisma.Decimal.ROUND_HALF_UP);
  let final=Prisma.Decimal.min(upper,Prisma.Decimal.max(lower,rounded));
  const guardrailClamped=!final.eq(rounded);
  const floor=product.costPrice===null?null:D(product.costPrice).mul(1+MIN_COST_MARKUP_PCT).toDecimalPlaces(digits,Prisma.Decimal.ROUND_CEIL);
  const marginClamped=floor===null?null:final.lt(floor);
  if(floor!==null)final=Prisma.Decimal.max(final,floor);
  const action=final.gt(current)?'raise':final.lt(current)?'lower':'hold';
  return {suggestedPrice:final.toNumber(),action:action as 'raise'|'lower'|'hold',guardrailClamped,marginClamped,
    floor:floor?.toNumber()??null,movementCapOverridden:final.gt(upper)};
}
export function localMarketTarget(currentPrice:number,average:number):number {
  const current=D(currentPrice),mean=D(average);
  return current.gt(mean.mul(1+COMPETITIVENESS_THRESHOLD_PCT))||current.lt(mean.mul(1-COMPETITIVENESS_THRESHOLD_PCT))?average:currentPrice;
}

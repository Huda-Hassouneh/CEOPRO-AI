import {COMPETITOR_AI_ACTIONS_ENABLED} from '../service/competitor-capabilities.js';
import {randomUUID} from 'node:crypto';
import type { Prisma } from '../../../generated/prisma/client.js';
import { marketTrackingConfig } from '../service/market-tracking.config.js';
export async function requestDiscovery(tx:Prisma.TransactionClient,tenantId:string,key?:string) {
 const config=marketTrackingConfig();
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return {...config,eventId:null,status:'INTEGRATION_DISABLED'};
 const dedupe=key ?? `catalog:${randomUUID()}`;
 const rows=await tx.$queryRaw<Array<{event_id:string;status:string}>>`SELECT * FROM public.queue_market_tracking(${tenantId}::uuid,'DISCOVERY',NULL,${dedupe})`;
 return {...config,eventId:rows[0]?.event_id ?? null,status:rows[0]?.status ?? 'NO_PRODUCTS_OR_ACCESS'};
}
export async function requestCollection(tx:Prisma.TransactionClient,tenantId:string,sourceId:string,minutes:number,dispatcher=false,dedupeKey?:string) {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return null;
 const key=dedupeKey ?? `collection:${sourceId}:${Math.floor(Date.now()/(minutes*60000))}`;
 if(dispatcher) {
  await tx.$executeRawUnsafe('SELECT pg_advisory_xact_lock(hashtextextended($1,0))',`market-source:${sourceId}`);
  const previous=await tx.$queryRaw<Array<{event_id:string;status:string}>>`SELECT event_id,status FROM market_tracking_outbox WHERE tenant_id=${tenantId}::uuid AND source_id=${sourceId}::uuid AND ((status<>'CANCELLED' AND worker_status<>'CANCELLED') OR last_error_code='COST_MARGIN_BLOCKED') AND (status='PENDING' OR created_at>now()-make_interval(mins=>${minutes})) ORDER BY created_at DESC LIMIT 1`;
  if(previous[0])return previous[0].status==='CANCELLED'?null:previous[0];
 }
 const rows=dispatcher ? await tx.$queryRaw<Array<{event_id:string;status:string}>>`INSERT INTO market_tracking_outbox AS o(tenant_id,kind,source_id,dedupe_key) VALUES(${tenantId}::uuid,'COLLECTION',${sourceId}::uuid,${key}) ON CONFLICT(tenant_id,dedupe_key) DO UPDATE SET dedupe_key=EXCLUDED.dedupe_key RETURNING o.event_id,o.status` : await tx.$queryRaw<Array<{event_id:string;status:string}>>`SELECT * FROM public.queue_market_tracking(${tenantId}::uuid,'COLLECTION',${sourceId}::uuid,${key})`; 
 return rows[0]?.status==='CANCELLED'?null:rows[0] ?? null;
}

export async function requestCompetitorDiscovery(tx:Prisma.TransactionClient,tenantId:string,competitorId:string) {
 if(!COMPETITOR_AI_ACTIONS_ENABLED) return {...marketTrackingConfig(),discoveryScope:'competitor' as const,eventId:null,status:'INTEGRATION_DISABLED'};
 const rows=await tx.$queryRaw<Array<{event_id:string;status:string}>>`SELECT * FROM public.queue_competitor_discovery(${tenantId}::uuid,${competitorId}::uuid,${randomUUID()})`;
 return {...marketTrackingConfig(),discoveryScope:'competitor' as const,eventId:rows[0]?.event_id ?? null,status:rows[0]?.status ?? 'NO_PRODUCTS_OR_ACCESS'};
}

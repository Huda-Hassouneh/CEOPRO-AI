import express,{Router} from 'express';
import {verifyShopifyWebhook} from './security.js';
import {StoreError} from '../contracts.js';
import {shopDomain,shopifySettings} from './domain.js';
import {createShopifyCallbackTicket} from './oauth.js';
const router=Router();
router.use((_req,res,next)=>{res.setHeader('Cache-Control','no-store');res.setHeader('Referrer-Policy','no-referrer');next();});
router.get('/callback',async(req,res)=>{
 try{const result=createShopifyCallbackTicket(new URL(req.originalUrl,'https://callback.invalid').searchParams);const url=new URL('/connect-data',shopifySettings().frontend);url.hash=new URLSearchParams({shopify_ticket:result.ticket,shopify_state:result.state}).toString();res.redirect(303,url.href);}
 catch(error){try{const url=new URL('/connect-data',shopifySettings().frontend);url.searchParams.set('shopify','error');url.searchParams.set('code',error instanceof StoreError?error.code:'STORE_SHOPIFY_AUTH_FAILED');res.redirect(303,url.href);}catch{res.status(503).json({success:false,code:'STORE_SHOPIFY_NOT_CONFIGURED'});}}
});
const topics=new Set(['app/uninstalled','products/create','products/update','products/delete','orders/create','orders/updated','orders/paid','orders/cancelled','refunds/create','inventory_levels/update','customers/data_request','customers/redact','shop/redact']);
router.post('/webhooks',express.raw({type:'application/json',limit:'2mb'}),async(req,res)=>{
 const secret=process.env.SHOPIFY_CLIENT_SECRET;if(!secret){res.status(503).end();return;}
 if(!Buffer.isBuffer(req.body)||!verifyShopifyWebhook(req.body,req.get('X-Shopify-Hmac-Sha256'),secret)){res.status(401).end();return;}
 try{
  const shop=shopDomain(req.get('X-Shopify-Shop-Domain')??''),topic=req.get('X-Shopify-Topic')??'',event=req.get('X-Shopify-Webhook-Id')??'';
  if(!topics.has(topic)||!event||event.length>200){res.status(400).end();return;}
  const body=JSON.parse(req.body.toString('utf8'));
  const orderIds=topic==='customers/redact'?body.orders_to_redact:topic==='customers/data_request'?body.orders_requested:topic==='products/delete'?[body.id]:[];
  if(orderIds!==undefined&&(!Array.isArray(orderIds)||orderIds.length>10000)){res.status(400).end();return;}
  const ids=(orderIds??[]).map((id:unknown)=>{if(typeof id!=='string'&&typeof id!=='number'||typeof id==='number'&&!Number.isSafeInteger(id)||!/^[1-9][0-9]{0,19}$/.test(String(id)))throw new StoreError('STORE_INVALID_REQUEST');return `gid://shopify/${topic==='products/delete'?'Product':'Order'}/${id}`;});
  const {marketDispatcherPrisma}=await import('../../../../config/market-dispatcher-database.js');
  await marketDispatcherPrisma.$queryRaw`SELECT public.process_shopify_event(${shop},${topic},${event},${ids}::text[])`;
  res.status(200).end();
 }catch{res.status(503).end();}
});
export default router;

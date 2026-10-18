import {COMPETITOR_AI_ACTIONS_ENABLED} from '../modules/competitors/service/competitor-capabilities.js';
if (!COMPETITOR_AI_ACTIONS_ENABLED) {
  console.info('[MarketTracking] Custom Node/Python worker bridge is disabled in this review release.');
  process.exit(0);
}
const {marketDispatcherPrisma} = await import('../config/market-dispatcher-database.js');
const {getRequiredEnv} = await import('../config/env.js');
const {scheduleMarketSources,dispatchMarketEvent} = await import('../modules/competitors/repo/market-dispatcher.repo.js');
if (process.env.MARKET_TRACKING_ENABLED !== "true")
  throw new Error(
    "Set MARKET_TRACKING_ENABLED=true after configuring the shared Python worker environment."
  );
const redisUrl = getRequiredEnv("MARKET_REDIS_URL");
const role = await marketDispatcherPrisma.$queryRaw<
  Array<{ current_user: string }>
>`SELECT current_user`;
if (role[0]?.current_user !== "ceopro_market_dispatcher")
  throw new Error(
    "MARKET_DISPATCHER_DATABASE_URL must use ceopro_market_dispatcher."
  );
let running = true;
process.on("SIGINT", () => {
  running = false;
});
process.on("SIGTERM", () => {
  running = false;
});
console.info(
  "[MarketTracking] Dispatcher started. Published means queued in Redis, not collected."
);
try {
  while (running) {
    try {
      const scheduled = await scheduleMarketSources(marketDispatcherPrisma);
      if (scheduled)
        console.info(
          `[MarketTracking] Scheduled ${scheduled} eligible sources.`
        );
      for (let i = 0; i < 20 && running; i++) {
        const result = await dispatchMarketEvent(
          marketDispatcherPrisma,
          redisUrl
        );
        if (!result) break;
        console.info(
          `[MarketTracking] ${result.eventId} ${result.status}${"errorCode" in result ? ` ${result.errorCode}` : ""}${"sourceId" in result ? ` source=${result.sourceId ?? "none"} tenant=${result.tenantId}` : ""}${"reason" in result && result.reason ? ` reason=${JSON.stringify(result.reason)}` : ""}`
        );
      }
    } catch {
      console.error(
        "[MarketTracking] Database/dispatch tick failed; pending events retained."
      );
    }
    if (running) await new Promise((resolve) => setTimeout(resolve, 10000));
  }
} finally {
  await marketDispatcherPrisma.$disconnect();
}

import { prisma } from "../config/database.js";
import { marketDispatcherPrisma } from "../config/market-dispatcher-database.js";
import { syncStorePage } from "../modules/dataconnection/store/sync.repo.js";
const roles = await Promise.all([
  prisma.$queryRaw<Array<{ current_user: string }>>`SELECT current_user`,
  marketDispatcherPrisma.$queryRaw<
    Array<{ current_user: string }>
  >`SELECT current_user`
]);
if (
  roles[0][0]?.current_user !== "ceopro_app" ||
  roles[1][0]?.current_user !== "ceopro_market_dispatcher"
)
  throw Error(
    "Store worker requires restricted application and scheduler roles"
  );
let running = true;
process.on("SIGINT", () => {
  running = false;
});
process.on("SIGTERM", () => {
  running = false;
});
const deferred = new Map<string, number>();
console.info(
  "[StoreSync] Started. Provider requests run outside database transactions."
);
try {
  while (running) {
    try {
      for (const [id, until] of deferred)
        if (until <= Date.now()) deferred.delete(id);
      const due = await marketDispatcherPrisma.$queryRaw<
        Array<{ tenant_id: string; source_id: string; actor_id: string }>
      >`SELECT tenant_id,source_id,actor_id FROM store_connections
   WHERE status IN ('QUEUED','CONNECTED','ERROR','SYNCING') AND attempts<5 AND next_run_at<=now() AND (lease_until IS NULL OR lease_until<=now())
    AND source_id<>ALL(${[...deferred.keys()]}::uuid[]) ORDER BY next_run_at,source_id LIMIT 2`;
      await Promise.allSettled(
        due.map(async (row) => {
          if (!running) return;
          try {
            const result = await syncStorePage(
              { tenantId: row.tenant_id, userId: row.actor_id },
              row.source_id
            );
            if (result.status === "IDLE")
              deferred.set(row.source_id, Date.now() + 10000);
            console.info("[StoreSync]", row.source_id, result);
          } catch {
            deferred.set(row.source_id, Date.now() + 300000);
            console.warn(
              "[StoreSync]",
              row.source_id,
              "Access unavailable; no data committed; recheck in 5 minutes"
            );
          }
        })
      );
    } catch {
      console.error(
        "[StoreSync] Scheduler unavailable; retained work will be retried."
      );
    }
    if (running) await new Promise((resolve) => setTimeout(resolve, 5000));
  }
} finally {
  await prisma.$disconnect();
  await marketDispatcherPrisma.$disconnect();
}

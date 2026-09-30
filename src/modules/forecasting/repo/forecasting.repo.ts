import { prisma } from "../../../config/database.js";
import { Prisma } from "../../../generated/prisma/client.js";

/** Read one consistent tenant snapshot. Membership is validated by middleware. */
export async function loadForecastData(tenantId: string, userId: string, start: Date, end: Date, productId = "all", detail = false) {
  return prisma.$transaction(async (tx) => {
    await tx.$queryRaw`SELECT set_config('app.current_tenant_id', ${tenantId}, true), set_config('app.current_user_id', ${userId}, true)`;
    const products = await tx.products.findMany({
      where: { tenant_id: tenantId, deleted_at: null },
      select: { product_id: true, product_name: true, category: true },
      orderBy: { product_id: "asc" }
    });
    if (productId !== "all" && !products.some(product => product.product_id === productId)) {
      return { products, inventory: [], forecasts: [], history: [] };
    }
    const scope = productId === "all" ? {} : { product_id: productId };
    const [inventory, forecasts, history] = await Promise.all([
      tx.inventory.findMany({ where: { tenant_id: tenantId, ...scope, products: { tenant_id: tenantId, deleted_at: null } } }),
      tx.demand_forecasts.findMany({
        where: {
          tenant_id: tenantId, ...scope, products: { tenant_id: tenantId, deleted_at: null },
          OR: [
            { forecast_start_date: { lte: end }, forecast_end_date: { gte: start } },
            { forecast_start_date: null, forecast_end_date: null, forecast_target_date: { gte: start, lte: end } }
          ]
        },
        include: { recommendation_outcomes: {
          where: { tenant_id: tenantId },
          orderBy: [{ created_at: { sort: "desc", nulls: "last" } }, { recommendation_id: "desc" }], take: 1
        } },
        orderBy: [{ created_at: { sort: "desc", nulls: "last" } }, { forecast_id: "desc" }]
      }),
      detail ? tx.$queryRaw<Array<{ date: string; units: bigint }>>`
        SELECT to_char(transaction_date AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS date,
               SUM(quantity_sold)::bigint AS units
        FROM transactions
        WHERE tenant_id = ${tenantId}::uuid AND product_id = ${productId}::uuid
          AND transaction_date >= ${start} AND transaction_date < ${end}
        GROUP BY 1 ORDER BY 1
      ` : Promise.resolve([])
    ]);
    return { products, inventory, forecasts, history };
  }, { isolationLevel: Prisma.TransactionIsolationLevel.RepeatableRead });
}

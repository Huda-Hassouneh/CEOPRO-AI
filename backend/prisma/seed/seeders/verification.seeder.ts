import { prisma } from "../../../src/config/database.js";
import { companies } from "../data/catalog.js";

export async function verifyDevelopmentSeed(args: {
  tenantIds: string[];
  users: any[];
  products: any[];
  competitors: any[];
  tracked: any[];
  mappings: any[];
  prices: any[];
  transactions: any[];
  reviews: any[];
  forecasts: any[];
  snapshots: any[];
}) {
  const {
    tenantIds,
    users,
    products,
    competitors,
    tracked,
    mappings,
    prices,
    transactions,
    reviews,
    forecasts,
    snapshots
  } = args;

  const identity = await prisma.$queryRaw<
    Array<{
      database: string;
      server: string;
      port: number;
      role: string;
      schema_name: string;
    }>
  >`
    SELECT current_database() AS database, inet_server_addr()::text AS server,
           inet_server_port() AS port, current_user AS role, current_schema() AS schema_name`;

  const counts = {
    tenants: await prisma.company.count({
      where: { id: { in: tenantIds } }
    }),
    users: await prisma.user.count({
      where: { userId: { in: users.map((user) => user.userId) } }
    }),
    products: await prisma.products.count({
      where: {
        product_id: { in: products.map((product) => product.product_id) }
      }
    }),
    competitors: await prisma.global_competitors.count({
      where: {
        global_competitor_id: {
          in: competitors.map(
            (competitor) => competitor.global_competitor_id
          )
        }
      }
    }),
    tenantCompetitors: await prisma.tenant_competitors.count({
      where: {
        OR: tracked.map((competitor) => ({
          tenant_id: competitor.tenant_id,
          global_competitor_id: competitor.global_competitor_id
        }))
      }
    }),
    mappings: await prisma.competitor_product_mappings.count({
      where: {
        mapping_id: { in: mappings.map((mapping) => mapping.mapping_id) }
      }
    }),
    prices: await prisma.competitor_prices.count({
      where: {
        competitor_price_id: {
          in: prices.map((price) => price.competitor_price_id)
        }
      }
    }),
    transactions: await prisma.transactions.count({
      where: {
        transaction_id: {
          in: transactions.map(
            (transaction) => transaction.transaction_id
          )
        }
      }
    }),
    reviews: await prisma.reviews.count({
      where: {
        review_id: { in: reviews.map((review) => review.review_id) }
      }
    }),
    forecasts: await prisma.demand_forecasts.count({
      where: {
        forecast_id: {
          in: forecasts.map((forecast) => forecast.forecast_id)
        }
      }
    }),
    snapshots: await prisma.competitor_score_snapshots.count({
      where: {
        score_id: {
          in: snapshots.map((snapshot) => snapshot.score_id)
        }
      }
    })
  };

  console.log("Seed database identity (no credentials):", identity[0]);
  console.log(
    "Verified fixture rows visible to the seed connection:",
    JSON.stringify(counts, null, 2)
  );

  if (
    counts.tenants !== companies.length ||
    counts.products !== products.length ||
    counts.transactions !== transactions.length
  ) {
    throw new Error(
      "Seed verification failed: tenant, product, or transaction rows are not visible; check RLS and the target database."
    );
  }

  return counts;
}

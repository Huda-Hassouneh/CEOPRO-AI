/** Deterministic, additive development fixtures. Run against a migrated TEST/DEV database as its migration owner. */
import { createHash } from "node:crypto";
import bcrypt from "bcryptjs";
import { prisma } from "../src/config/database.js";

const url = process.env.DATABASE_URL;
const dbName = url ? decodeURIComponent(new URL(url).pathname.slice(1)) : "";
if (!/test|dev/i.test(dbName) || process.env.NODE_ENV === "production") {
  throw new Error(
    "Refusing to seed: DATABASE_URL database name must contain TEST or DEV and NODE_ENV must not be production"
  );
}
const uuid = (key: string) => {
  const h = createHash("sha256")
    .update(`ceopro-fixture-v1:${key}`)
    .digest("hex");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-4${h.slice(13, 16)}-a${h.slice(17, 20)}-${h.slice(20, 32)}`;
};
const now = new Date();
const ago = (days: number) => new Date(now.getTime() - days * 86400000);
const companies = [
  ["Northstar Retail Labs", "JO", "JOD", "Asia/Amman"],
  ["Cedar Commerce Demo", "JO", "JOD", "Asia/Amman"],
  ["Atlas Foods Test Group", "AE", "AED", "Asia/Dubai"],
  ["Meridian Office Supply Demo", "US", "USD", "America/New_York"],
  ["Amman Home Market", "JO", "JOD", "Asia/Amman"],
  ["Levant Electronics Demo", "SA", "SAR", "Asia/Riyadh"]
] as const;
const catalog = [
  ["Wireless ANC Headphones", "Electronics", 85],
  ["Smart Air Purifier", "Electronics", 130],
  ["Premium Espresso Machine", "Home", 220],
  ["Ergonomic Office Chair", "Home", 160],
  ["Organic Olive Oil 1L", "Grocery", 18],
  ["Single Origin Coffee Beans", "Grocery", 24],
  ["Vitamin C Face Serum", "Wellness", 32],
  ["Ceramic Water Filter", "Wellness", 48],
  ["Portable USB-C Charger", "Electronics", 38],
  ["Desk Organizer", "Home", 27],
  ["Dark Chocolate Gift Box", "Grocery", 21],
  ["Daily Sunscreen SPF50", "Wellness", 28],
  ["Bluetooth Speaker", "Electronics", 65],
  ["Linen Table Lamp", "Home", 72],
  ["Herbal Tea Collection", "Grocery", 16],
  ["Hydrating Hand Cream", "Wellness", 14],
  ["Wireless Keyboard", "Electronics", 54],
  ["Stainless Steel Kettle", "Home", 56],
  ["Almond Butter Jar", "Grocery", 19],
  ["Travel Toiletry Kit", "Wellness", 35]
] as const;
const competitorNames = [
  "Juniper Outlet",
  "Orion Marketplace",
  "Crescent Direct",
  "Summit Goods",
  "Harbor Store",
  "Palm Retail",
  "Beacon Supply",
  "Copper Cart",
  "Evergreen Shop",
  "Willow Market",
  "Silverline Trade",
  "Vista Merchants",
  "Pioneer Store",
  "Bluebird Commerce",
  "Olive Branch Market",
  "Coral Goods",
  "Amber Retail",
  "Delta Direct",
  "Maple Supply",
  "Horizon Outlet",
  "Dune Commerce",
  "Pearl Store",
  "Stonebridge Retail",
  "Spruce Market"
];
const roles = ["owner", "admin", "manager", "accountant", "staff"];
const chunk = async <T>(items: T[], fn: (batch: T[]) => Promise<unknown>) => {
  for (let i = 0; i < items.length; i += 400) await fn(items.slice(i, i + 400));
};
async function main() {
  const installed = await prisma.systemRole.findMany({
    where: { roleKey: { in: roles } }
  });
  if (installed.length !== roles.length)
    throw new Error(
      "Migrated system_roles are missing; apply the canonical migration chain first"
    );
  const password = process.env.SEED_DEV_PASSWORD;
  if (!password || password.length < 12)
    throw new Error(
      "Set SEED_DEV_PASSWORD (12+ characters); no default password is embedded in the fixtures"
    );
  const passwordHash = await bcrypt.hash(password, 12);
  const tenantIds = companies.map((_, i) => uuid(`tenant:${i}`));
  await prisma.company.createMany({
    data: companies.map(
      ([businessName, countryCode, primaryCurrency, timezone], i) => ({
        id: tenantIds[i],
        businessName,
        businessType: i === 2 ? "Food retail" : "Retail",
        countryCode,
        primaryCurrency,
        supportedCurrencies: [primaryCurrency],
        timezone,
        platformStatus: i === 5 ? "suspended" : "active"
      })
    ),
    skipDuplicates: true
  });
  const users = companies.flatMap((_, t) =>
    roles.map((role, r) => ({
      userId: uuid(`user:${t}:${r}`),
      email: `${role}.${t + 1}@example.com`,
      fullName: `${["Maya", "Omar", "Lina", "Samir", "Nour"][r]} ${["Haddad", "Nasser", "Salem", "Khalil", "Farah", "Karim"][t]}`,
      passwordHash
    }))
  );
  await prisma.user.createMany({ data: users, skipDuplicates: true });
  await prisma.tenantUser.createMany({
    data: users.map((u, i) => ({
      id: uuid(`membership:${i}`),
      tenantId: tenantIds[Math.floor(i / 5)],
      userId: u.userId,
      roleKey: roles[i % 5],
      removedAt: i === 29 ? ago(8) : null
    })),
    skipDuplicates: true
  });
  await prisma.authSession.createMany({
    data: users.map((u, i) => ({
      id: uuid(`session:${i}`),
      userId: u.userId,
      tenantId: tenantIds[Math.floor(i / 5)],
      device: "Development browser",
      expiresAt: ago(i % 7 === 0 ? 2 : -30),
      revokedAt: i % 9 === 0 ? ago(2) : null
    })),
    skipDuplicates: true
  });
  await prisma.platformInvitation.createMany({
    data: tenantIds.flatMap((tenantId, t) =>
      [0, 1].map((k) => ({
        id: uuid(`invitation:${t}:${k}`),
        tenantId,
        email: `invite.${t + 1}.${k + 1}@example.com`,
        roleKey: k ? "manager" : "staff",
        invitedBy: users[t * 5].userId,
        tokenHash: createHash("sha256")
          .update(`ceopro-invitation-fixture:${t}:${k}`)
          .digest("hex"),
        status: "pending",
        expiresAt: ago(k ? 5 : -10)
      }))
    ),
    skipDuplicates: true
  });
  const planId = uuid("plan:demo");
  await prisma.plan.createMany({
    data: [
      {
        id: planId,
        name: "Development Showcase",
        name_ar: "عرض تجريبي",
        description:
          "Synthetic integration fixture; no external payment provider is connected.",
        price: 49,
        currency: "JOD",
        billingIntervalValue: 1,
        billingIntervalUnit: "month"
      }
    ],
    skipDuplicates: true
  });
  const subscriptions = tenantIds.map((tenantId, i) => ({
    id: uuid(`subscription:${i}`),
    tenantId,
    planId,
    paymentProvider: "fixture",
    status: ["active", "trialing", "active", "canceled", "active", "past_due"][
      i
    ],
    currentPeriodStart: ago(i === 3 ? 70 : 15),
    currentPeriodEnd: ago(i === 3 ? 40 : i === 0 ? -2 : -15),
    cancelAtPeriodEnd: i === 2,
    cancelledAt: i === 3 ? ago(40) : null
  }));
  await prisma.subscription.createMany({
    data: subscriptions,
    skipDuplicates: true
  });
  await prisma.paymentTransaction.createMany({
    data: subscriptions
      .filter((_, i) => i !== 1)
      .map((sub, i) => ({
        id: uuid(`payment:${i}`),
        subscriptionId: sub.id,
        amount: 49,
        currency: "JOD",
        status: i === 4 ? "failed" : "succeeded",
        paidAt: i === 4 ? null : ago(14)
      })),
    skipDuplicates: true
  });
  const products = companies.flatMap(([, , currency], t) =>
    (t === 4 ? catalog.slice(0, 5) : catalog).map(
      ([name, category, base], p) => ({
        product_id: uuid(`product:${t}:${p}`),
        tenant_id: tenantIds[t],
        product_name: { en: name },
        category: { en: category },
        brand: {
          en: `${["Northstar", "Cedar", "Atlas", "Meridian", "Amman", "Levant"][t]} Select`
        },
        current_price: +(base * (1 + t * 0.04) + (p % 3)).toFixed(2),
        cost_price: +(base * 0.58).toFixed(2),
        currency,
        source: "MANUAL",
        created_at: ago(180 - p * 2),
        metadata: { fixture: "ceopro-v1" }
      })
    )
  );
  await chunk(products, (batch) =>
    prisma.products.createMany({ data: batch, skipDuplicates: true })
  );
  const inventory = products.map((p, i) => ({
    tenant_id: p.tenant_id,
    product_id: p.product_id,
    inventory_id: uuid(`inventory:${i}`),
    stock_quantity: i % 17 === 0 ? 0 : i % 11 === 0 ? 4 : 60 + (i % 90),
    reorder_level: 12
  }));
  await chunk(inventory, (batch) =>
    prisma.inventory.createMany({ data: batch, skipDuplicates: true })
  );
  await prisma.rag_documents_metadata.createMany({
    data: tenantIds.flatMap((tenant_id, t) =>
      ["Pending", "Processed", "Failed"].map((processed_status, j) => ({
        document_id: uuid(`document:${t}:${j}`),
        tenant_id,
        file_name: `${["inventory-guide", "catalog-notes", "failed-import"][j]}.txt`,
        storage_bucket_path: `fixtures/ceopro-v1/${t}/${j}.txt`,
        file_size_bytes: BigInt(1024 + j * 120),
        content_type: "text/plain",
        uploaded_by_user_id: users[t * 5].userId,
        processed_status
      }))
    ),
    skipDuplicates: true
  });
  const competitors = competitorNames.map((name, i) => ({
    global_competitor_id: uuid(`competitor:${i}`),
    competitor_name: name,
    visibility: "GLOBAL",
    country_code: i % 3 ? "JO" : "AE"
  }));
  await prisma.global_competitors.createMany({
    data: competitors,
    skipDuplicates: true
  });
  const tracked = companies.flatMap((_, t) =>
    competitors
      .slice(0, t === 4 ? 0 : t === 0 ? 24 : 8 + t * 2)
      .map((c, i) => ({
        tenant_id: tenantIds[t],
        global_competitor_id: c.global_competitor_id,
        is_confirmed_competitor: i % 5 !== 4 && i % 3 === 0,
        product_match_rate: i % 5 === 4 ? 0.15 : 0.8,
        tier: i % 5 === 4 ? "CANDIDATE" : i % 3 === 0 ? "STRATEGIC" : "RELEVANT"
      }))
  );
  await chunk(tracked, (batch) =>
    prisma.tenant_competitors.createMany({ data: batch, skipDuplicates: true })
  );
  const mappings = products.flatMap((p, ix) => {
    const t = tenantIds.indexOf(p.tenant_id);
    if (t === 4 || ix % 20 === 19) return [];
    const n = t === 0 && ix === 0 ? 8 : ix % 6 === 0 ? 1 : 3;
    return Array.from({ length: n }, (_, k) => ({
      mapping_id: uuid(`mapping:${ix}:${k}`),
      tenant_id: p.tenant_id,
      product_id: p.product_id,
      global_competitor_id:
        competitors[(ix + k) % (t === 0 ? 24 : 8 + t * 2)].global_competitor_id
    }));
  });
  await chunk(mappings, (batch) =>
    prisma.competitor_product_mappings.createMany({
      data: batch,
      skipDuplicates: true
    })
  );
  const byProduct = new Map(products.map((p) => [p.product_id, p]));
  const prices = mappings.flatMap((m, ix) =>
    ix % 13 === 0
      ? []
      : Array.from({ length: ix % 5 === 0 ? 2 : 6 }, (_, k) => ({
          competitor_price_id: uuid(`price:${ix}:${k}`),
          tenant_id: m.tenant_id,
          mapping_id: m.mapping_id,
          scraped_price: +(
            Number(byProduct.get(m.product_id)!.current_price) *
            (0.78 + (ix % 7) * 0.06 + k * 0.004)
          ).toFixed(2),
          currency: byProduct.get(m.product_id)!.currency,
          observed_at: ago((5 - k) * 14 + (ix % 6)),
          source_status: "ALLOWED",
          is_exact_data: true
        }))
  );
  await chunk(prices, (batch) =>
    prisma.competitor_prices.createMany({ data: batch, skipDuplicates: true })
  );
  const transactions = products.flatMap((p, ix) =>
    Array.from({ length: ix % 13 === 0 ? 4 : 32 }, (_, k) => {
      const quantity_sold = 1 + ((k + ix) % 5);
      const unit_price = Number(p.current_price);
      return {
        transaction_id: uuid(`sale:${ix}:${k}`),
        tenant_id: p.tenant_id,
        product_id: p.product_id,
        quantity_sold,
        unit_price,
        total_price: +(quantity_sold * unit_price).toFixed(4),
        original_currency: p.currency,
        transaction_date: ago((k * 11 + ix * 3) % 360),
        sale_source: k % 4 ? "POS" : "IMPORT"
      };
    })
  );
  await chunk(transactions, (batch) =>
    prisma.transactions.createMany({ data: batch, skipDuplicates: true })
  );
  const reviews = products.flatMap((p, ix) =>
    Array.from({ length: ix % 11 === 0 ? 1 : 8 }, (_, k) => {
      const rating = ((ix + k) % 5) + 1;
      return {
        review_id: uuid(`review:${ix}:${k}`),
        tenant_id: p.tenant_id,
        product_id: p.product_id,
        subject_type: "PRODUCT",
        source_platform: "DEMO_IMPORT",
        reviewer_name: `Demo customer ${k + 1}`,
        review_text:
          rating >= 4
            ? "Reliable quality and prompt delivery."
            : rating <= 2
              ? "The product did not meet my expectations."
              : "Good overall, with room to improve packaging.",
        review_rating: rating,
        review_date: ago((ix * 5 + k * 9) % 240),
        source_status: "ALLOWED",
        collection_method: "MANUAL"
      };
    })
  );
  await chunk(reviews, (batch) =>
    prisma.reviews.createMany({ data: batch, skipDuplicates: true })
  );
  const forecasts = products
    .filter((_, i) => i % 9 !== 0)
    .flatMap((p, productIndex) => {
      const rows = [];

      // Previous 30-day forecast:
      // today - 30 days through yesterday.
      for (let day = 0; day < 30; day++) {
        const forecastDate = ago(30 - day);

        const baseDemand = 2 + (productIndex % 8);

        // Deterministic daily variation.
        const dailyDemand =
          baseDemand + ((day + productIndex) % 4) + Math.floor(day / 10);

        rows.push({
          forecast_id: uuid(`forecast:${p.product_id}:previous:${day}`),
          tenant_id: p.tenant_id,
          product_id: p.product_id,

          // A daily forecast is represented by a one-day interval.
          forecast_start_date: forecastDate,
          forecast_end_date: forecastDate,
          forecast_target_date: forecastDate,

          expected_demand: dailyDemand,

          confidence_range_lower: Math.max(0, dailyDemand - 2),
          confidence_range_upper: dailyDemand + 3,

          model_version: "synthetic-integration-v2-daily",

          features_used: {
            fixture: true,
            granularity: "daily",
            horizon: "previous-30-days"
          },

          // Ensure the prediction existed before the forecasted date.
          created_at: ago(31)
        });
      }

      // Current / future 30-day forecast:
      // today through today + 29 days.
      for (let day = 0; day < 30; day++) {
        const forecastDate = ago(-day);

        const baseDemand = 3 + (productIndex % 9);

        /*
         * Produce deterministic examples of all three trends:
         *
         * productIndex % 3 === 0 -> increasing
         * productIndex % 3 === 1 -> decreasing
         * productIndex % 3 === 2 -> stable
         */
        let dailyDemand: number;

        switch (productIndex % 3) {
          case 0:
            dailyDemand = baseDemand + Math.floor(day / 5);
            break;

          case 1:
            dailyDemand = Math.max(1, baseDemand + 6 - Math.floor(day / 5));
            break;

          default:
            dailyDemand = baseDemand;
            break;
        }

        rows.push({
          forecast_id: uuid(`forecast:${p.product_id}:current:${day}`),
          tenant_id: p.tenant_id,
          product_id: p.product_id,

          forecast_start_date: forecastDate,
          forecast_end_date: forecastDate,
          forecast_target_date: forecastDate,

          expected_demand: dailyDemand,

          confidence_range_lower: Math.max(0, dailyDemand - 2),
          confidence_range_upper: dailyDemand + 3,

          model_version: "synthetic-integration-v2-daily",

          features_used: {
            fixture: true,
            granularity: "daily",
            horizon: "next-30-days"
          },

          created_at: now
        });
      }

      return rows;
    });
  await chunk(forecasts, (batch) =>
    prisma.demand_forecasts.createMany({ data: batch, skipDuplicates: true })
  );
  const snapshots = tracked
    .filter((x, i) => i % 7 !== 0)
    .flatMap((x, i) =>
      [0, 1].map((k) => ({
        score_id: uuid(
          `snapshot:${x.tenant_id}:${x.global_competitor_id}:${k}`
        ),
        tenant_id: x.tenant_id,
        global_competitor_id: x.global_competitor_id,
        price_score: 50 + (i % 35),
        composite_score: 44 + (i % 45) + k,
        missing_factors: ["sentiment", "market_activity"],
        evidence: { fixture: "synthetic-integration-v1" },
        calculated_at: ago(k ? 30 : 1)
      }))
    );
  await chunk(snapshots, (batch) =>
    prisma.competitor_score_snapshots.createMany({
      data: batch,
      skipDuplicates: true
    })
  );
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
    tenants: await prisma.company.count({ where: { id: { in: tenantIds } } }),
    users: await prisma.user.count({
      where: { userId: { in: users.map((u) => u.userId) } }
    }),
    products: await prisma.products.count({
      where: { product_id: { in: products.map((p) => p.product_id) } }
    }),
    competitors: await prisma.global_competitors.count({
      where: {
        global_competitor_id: {
          in: competitors.map((c) => c.global_competitor_id)
        }
      }
    }),
    tenantCompetitors: await prisma.tenant_competitors.count({
      where: {
        OR: tracked.map((c) => ({
          tenant_id: c.tenant_id,
          global_competitor_id: c.global_competitor_id
        }))
      }
    }),
    mappings: await prisma.competitor_product_mappings.count({
      where: { mapping_id: { in: mappings.map((m) => m.mapping_id) } }
    }),
    prices: await prisma.competitor_prices.count({
      where: {
        competitor_price_id: { in: prices.map((p) => p.competitor_price_id) }
      }
    }),
    transactions: await prisma.transactions.count({
      where: {
        transaction_id: { in: transactions.map((t) => t.transaction_id) }
      }
    }),
    reviews: await prisma.reviews.count({
      where: { review_id: { in: reviews.map((r) => r.review_id) } }
    }),
    forecasts: await prisma.demand_forecasts.count({
      where: { forecast_id: { in: forecasts.map((f) => f.forecast_id) } }
    }),
    snapshots: await prisma.competitor_score_snapshots.count({
      where: { score_id: { in: snapshots.map((s) => s.score_id) } }
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
      "Seed verification failed: tenant, product, or transaction rows are not visible; check RLS and the target database"
    );
  }
}
main()
  .catch((e) => {
    console.error(e);
    process.exitCode = 1;
  })
  .finally(() => prisma.$disconnect());

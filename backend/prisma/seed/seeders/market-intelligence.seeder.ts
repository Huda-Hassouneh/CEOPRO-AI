import { prisma } from "../../../src/config/database.js";
import { companies, competitorNames } from "../data/catalog.js";
import { inBatches } from "../helpers/batch.js";
import type { SeedClock } from "../helpers/time.js";

export async function seedMarketIntelligence(args: {
  tenantIds: string[];
  products: any[];
  uuid: (key: string) => string;
  clock: SeedClock;
}) {
  const { tenantIds, products, uuid, clock } = args;

  const competitors = competitorNames.map((name, index) => ({
    global_competitor_id: uuid(`competitor:${index}`),
    competitor_name: name,
    visibility: "GLOBAL",
    country_code: index % 3 ? "JO" : "AE"
  }));

  await prisma.global_competitors.createMany({
    data: competitors,
    skipDuplicates: true
  });

  const tracked = companies.flatMap((_, tenantIndex) =>
    competitors
      .slice(
        0,
        tenantIndex === 4 ? 0 : tenantIndex === 0 ? 24 : 8 + tenantIndex * 2
      )
      .map((competitor, index) => ({
        tenant_id: tenantIds[tenantIndex],
        global_competitor_id: competitor.global_competitor_id,
        is_confirmed_competitor: index % 5 !== 4 && index % 3 === 0,
        product_match_rate: index % 5 === 4 ? 0.15 : 0.8,
        tier:
          index % 5 === 4
            ? "CANDIDATE"
            : index % 3 === 0
              ? "STRATEGIC"
              : "RELEVANT"
      }))
  );

  await inBatches(tracked, (batch) =>
    prisma.tenant_competitors.createMany({ data: batch, skipDuplicates: true })
  );

  const mappings = products.flatMap((product, productIndex) => {
    const tenantIndex = tenantIds.indexOf(product.tenant_id);

    if (tenantIndex === 4 || productIndex % 20 === 19) {
      return [];
    }

    const mappingCount =
      tenantIndex === 0 && productIndex === 0
        ? 8
        : productIndex % 6 === 0
          ? 1
          : 3;

    return Array.from({ length: mappingCount }, (_, mappingIndex) => ({
      mapping_id: uuid(`mapping:${productIndex}:${mappingIndex}`),
      tenant_id: product.tenant_id,
      product_id: product.product_id,
      global_competitor_id:
        competitors[
          (productIndex + mappingIndex) %
            (tenantIndex === 0 ? 24 : 8 + tenantIndex * 2)
        ].global_competitor_id
    }));
  });

  await inBatches(mappings, (batch) =>
    prisma.competitor_product_mappings.createMany({
      data: batch,
      skipDuplicates: true
    })
  );

  const byProduct = new Map(
    products.map((product) => [product.product_id, product])
  );

  const prices = mappings.flatMap((mapping, mappingIndex) =>
    mappingIndex % 13 === 0
      ? []
      : Array.from(
          { length: mappingIndex % 5 === 0 ? 2 : 6 },
          (_, observationIndex) => {
            const product = byProduct.get(mapping.product_id)!;

            return {
              competitor_price_id: uuid(
                `price:${mappingIndex}:${observationIndex}`
              ),
              tenant_id: mapping.tenant_id,
              mapping_id: mapping.mapping_id,
              scraped_price: +(
                Number(product.current_price) *
                (0.78 +
                  (mappingIndex % 7) * 0.06 +
                  observationIndex * 0.004)
              ).toFixed(2),
              currency: product.currency,
              observed_at: clock.ago(
                (5 - observationIndex) * 14 + (mappingIndex % 6)
              ),
              source_status: "ALLOWED",
              is_exact_data: true
            };
          }
        )
  );

  await inBatches(prices, (batch) =>
    prisma.competitor_prices.createMany({ data: batch, skipDuplicates: true })
  );

  const snapshots = tracked
    .filter((_, index) => index % 7 !== 0)
    .flatMap((trackedCompetitor, index) =>
      [0, 1].map((historyIndex) => ({
        score_id: uuid(
          `snapshot:${trackedCompetitor.tenant_id}:${trackedCompetitor.global_competitor_id}:${historyIndex}`
        ),
        tenant_id: trackedCompetitor.tenant_id,
        global_competitor_id: trackedCompetitor.global_competitor_id,
        price_score: 50 + (index % 35),
        composite_score: 44 + (index % 45) + historyIndex,
        missing_factors: ["sentiment", "market_activity"],
        evidence: { fixture: "synthetic-integration-v1" },
        calculated_at: clock.ago(historyIndex ? 30 : 1)
      }))
    );

  await inBatches(snapshots, (batch) =>
    prisma.competitor_score_snapshots.createMany({
      data: batch,
      skipDuplicates: true
    })
  );

  return { competitors, tracked, mappings, prices, snapshots };
}

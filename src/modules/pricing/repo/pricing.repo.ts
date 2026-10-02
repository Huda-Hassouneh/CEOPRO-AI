import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type {
  MarketPricePoint,
  PricingEvidence,
  PricingProductContext
} from "../types/pricing.types.js";

async function setTenantContext(
  tx: Prisma.TransactionClient,
  tenantId: string,
  userId: string
): Promise<void> {
  await tx.$queryRaw`
    SELECT
      set_config('app.current_tenant_id', ${tenantId}, true),
      set_config('app.current_user_id', ${userId}, true)
  `;
}

export async function getProductPricingContext(
  tenantId: string,
  userId: string,
  productId: string
): Promise<PricingProductContext | null> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, tenantId, userId);

    const product = await tx.products.findFirst({
      where: {
        tenant_id: tenantId,
        product_id: productId,
        deleted_at: null
      },
      select: {
        product_id: true,
        current_price: true,
        currency: true
      }
    });

    if (!product) return null;

    return {
      productId: product.product_id,
      currentPrice: Number(product.current_price),
      currency: product.currency
    };
  });
}

export async function getLatestEligibleMarketPrices(input: {
  tenantId: string;
  userId: string;
  productId: string;
  currency: string;
  observedAfter: Date;
  observedBefore: Date;
}): Promise<MarketPricePoint[]> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);

    const mappings = await tx.competitor_product_mappings.findMany({
      where: {
        tenant_id: input.tenantId,
        product_id: input.productId,
        is_active: true,
        tenant_competitors: {
          is_tracked: true
        }
      },
      select: {
        mapping_id: true,
        global_competitor_id: true,
        competitor_prices: {
          where: {
            is_available: true,
            is_exact_data: true,
            source_status: "ALLOWED",
            currency: input.currency,
            observed_at: {
              gte: input.observedAfter,
              lte: input.observedBefore
            }
          },
          orderBy: [
            { observed_at: "desc" },
            { competitor_price_id: "desc" }
          ],
          select: {
            competitor_price_id: true,
            scraped_price: true,
            currency: true,
            observed_at: true
          }
        }
      }
    });

    return mappings.flatMap((mapping) =>
      mapping.competitor_prices.map((price) => ({
        competitorPriceId: price.competitor_price_id,
        mappingId: mapping.mapping_id,
        competitorId: mapping.global_competitor_id,
        price: Number(price.scraped_price),
        currency: price.currency,
        observedAt: price.observed_at
      }))
    );
  });
}

export async function getPricingEvidence(
  tenantId: string,
  userId: string,
  evidenceId: string
): Promise<PricingEvidence | null> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, tenantId, userId);

    const evidence = await tx.evidence_records.findFirst({
      where: {
        tenant_id: tenantId,
        evidence_id: evidenceId
      },
      select: {
        evidence_id: true,
        explanation_text: true,
        confidence_score: true,
        generated_at: true
      }
    });

    if (!evidence) return null;

    return {
      evidenceId: evidence.evidence_id,
      explanationText: evidence.explanation_text,
      confidenceScore:
        evidence.confidence_score == null
          ? null
          : Number(evidence.confidence_score),
      generatedAt: evidence.generated_at
    };
  });
}

import { prisma } from "../../../config/database.js";
import type { Prisma } from "../../../generated/prisma/client.js";
import type {
  MarketPricePoint,
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

function readProductName(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  for (const key of ["en", "ar"]) {
    const candidate = record[key];
    if (typeof candidate === "string" && candidate.trim()) {
      return candidate.trim();
    }
  }
  return null;
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
        product_name: true,
        current_price: true,
        cost_price: true,
        currency: true
      }
    });

    if (!product) return null;
    const productName = readProductName(product.product_name);
    if (!productName) return null;

    return {
      productId: product.product_id,
      productName,
      currentPrice: Number(product.current_price),
      costPrice:
        product.cost_price == null ? null : Number(product.cost_price),
      currency: product.currency
    };
  });
}

export async function getEligibleMarketPrices(input: {
  tenantId: string;
  userId: string;
  productId: string;
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
        tenant_competitors: { is_tracked: true }
      },
      select: {
        mapping_id: true,
        global_competitor_id: true,
        tenant_competitors: {
          select: {
            custom_alias: true,
            global_competitors: { select: { competitor_name: true } }
          }
        },
        competitor_prices: {
          where: {
            is_available: true,
            is_exact_data: true,
            source_status: "ALLOWED",
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
        competitorName:
          mapping.tenant_competitors.custom_alias?.trim() ||
          mapping.tenant_competitors.global_competitors.competitor_name,
        price: Number(price.scraped_price),
        currency: price.currency,
        observedAt: price.observed_at
      }))
    );
  });
}

export async function getExchangeRates(input: {
  fromCurrencies: string[];
  toCurrency: string;
}): Promise<
  Array<{
    fromCurrency: string;
    toCurrency: string;
    rate: number;
    asOf: Date;
    source: string;
  }>
> {
  const currencies = [...new Set(input.fromCurrencies)].filter(
    (currency) => currency !== input.toCurrency
  );
  if (currencies.length === 0) return [];

  const rows = await prisma.currency_rates.findMany({
    where: {
      from_currency: { in: currencies },
      to_currency: input.toCurrency
    },
    select: {
      from_currency: true,
      to_currency: true,
      exchange_rate: true,
      last_fetched: true,
      source: true
    }
  });

  return rows.map((row) => ({
    fromCurrency: row.from_currency,
    toCurrency: row.to_currency,
    rate: Number(row.exchange_rate),
    asOf: row.last_fetched ?? new Date(0),
    source: row.source?.trim() || "unspecified"
  }));
}

export async function persistPricingRecommendation(input: {
  tenantId: string;
  userId: string;
  productId: string;
  status: "OK" | "UNKNOWN";
  action: "raise" | "lower" | "hold" | null;
  currentPrice: number;
  suggestedPrice: number | null;
  confidenceScore: number | null;
  explanationText: string | null;
  matchedCompetitorCount: number;
  guardrailClamped: boolean | null;
  marginGuardrailClamped: boolean | null;
}): Promise<{ evidenceId: string; outcomeId: string | null }> {
  return prisma.$transaction(async (tx) => {
    await setTenantContext(tx, input.tenantId, input.userId);

    const evidence = await tx.evidence_records.create({
      data: {
        tenant_id: input.tenantId,
        source_module: "pricing",
        metric_name: "price_recommendation",
        metric_value_json: {
          status: input.status,
          product_id: input.productId,
          current_price: input.currentPrice,
          suggested_price: input.suggestedPrice,
          matched_competitor_count: input.matchedCompetitorCount,
          guardrail_clamped: input.guardrailClamped,
          margin_guardrail_clamped: input.marginGuardrailClamped
        },
        source_record_ids: { product_id: input.productId },
        confidence_score: input.confidenceScore,
        explanation_text: input.explanationText
      },
      select: { evidence_id: true }
    });

    if (input.status !== "OK" || !input.action) {
      return { evidenceId: evidence.evidence_id, outcomeId: null };
    }

    const outcome = await tx.recommendation_outcomes.create({
      data: {
        tenant_id: input.tenantId,
        evidence_id: evidence.evidence_id,
        recommended_action: input.action,
        expected_impact_json: {
          product_id: input.productId,
          current_price: input.currentPrice,
          suggested_price: input.suggestedPrice,
          matched_competitor_count: input.matchedCompetitorCount
        }
      },
      select: { recommendation_id: true }
    });

    return {
      evidenceId: evidence.evidence_id,
      outcomeId: outcome.recommendation_id
    };
  });
}

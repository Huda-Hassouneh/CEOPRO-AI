import * as marketIntelligenceRepo from "../repo/market-int.repo.js";
import { getFeatureAccessInfo } from "../../features/repo/usage.repo.js";
import { getMpiSummary } from "../../mpi/service/mpi.service.js";
import type { MpiLabelCounts } from "../../mpi/types/mpi.types.js";

type MarketPerceptionLabel = "positive" | "neutral" | "negative";

const getDominantPerceptionLabel = (
  counts: MpiLabelCounts
): MarketPerceptionLabel | null => {
  const entries = [
    ["positive", counts.positive],
    ["neutral", counts.neutral],
    ["negative", counts.negative]
  ] as const;

  const maxCount = Math.max(...entries.map(([, count]) => count));
  const winners = entries.filter(([, count]) => count === maxCount);

  // Do not invent a qualitative conclusion when the documented
  // positive/neutral/negative counts are tied.
  return winners.length === 1 ? winners[0][0] : null;
};

type EnrichedMarketPerception<T> = Omit<
  T,
  "marketPerception" | "marketPerceptionScore"
> & {
  marketPerception: MarketPerceptionLabel | null;
  marketPerceptionScore: number | null;
};

const enrichMarketPerception = async <T extends { competitorId: string }>(
  competitor: T,
  authorization: string
): Promise<EnrichedMarketPerception<T>> => {
  try {
    const mpi = await getMpiSummary({
      subjectType: "COMPETITOR",
      subjectId: competitor.competitorId,
      authorization
    });
    console.log({ mpi });

    if (mpi.status !== "OK") {
      return {
        ...competitor,
        marketPerception: null,
        marketPerceptionScore: null
      };
    }

    // CEOPRO's AI implementation treats LOW_SAMPLE_SIZE as insufficient
    // evidence for a reliable market conclusion. Keep the page unavailable
    // instead of presenting a weak result as authoritative.
    if (mpi.sample_size.status !== "OK") {
      return {
        ...competitor,
        marketPerception: null,
        marketPerceptionScore: null
      };
    }

    return {
      ...competitor,
      // Existing frontend contract: qualitative ToneBadge value.
      marketPerception: getDominantPerceptionLabel(mpi.label_counts),
      // Authoritative MPI value from CEOPRO_API_Reference: 0..100.
      marketPerceptionScore: Number(mpi.mpi.toFixed(1))
    };
  } catch (error) {
    console.warn(
      `MPI enrichment failed for competitor ${competitor.competitorId}:`,
      error instanceof Error ? error.message : error
    );

    // MPI is an optional enrichment of the Market Intelligence payload.
    // Do not fail the rest of the page when the external AI service is
    // unavailable or returns an invalid response.
    return {
      ...competitor,
      marketPerception: null,
      marketPerceptionScore: null
    };
  }
};

export const getMarketIntelligence = async (
  tenantId: string,
  productId?: string,
  periodDays?: number,
  authorization?: string
) => {
  const data = await marketIntelligenceRepo.getMarketIntelligence(
    tenantId,
    productId,
    periodDays
  );

  if (!data) {
    return {
      companyId: tenantId,
      period: { days: periodDays ?? 30 },
      availablePeriods: [30, 90],
      products: [],
      selectedProduct: null,
      metrics: [],
      aiMarketIntelligence: null,
      expansionOpportunities: [],
      competitors: [],
      pricingRecommendations: [],
      recentPriceChanges: []
    };
  }

  if (!authorization || data.competitors.length === 0) {
    return data;
  }

  let hasMarketPerceptionAccess = false;

  try {
    const { subscription, planFeature } = await getFeatureAccessInfo(
      tenantId,
      "market_perception"
    );
    hasMarketPerceptionAccess = Boolean(subscription && planFeature);
  } catch (error) {
    console.warn(
      "Unable to verify market_perception access for Market Intelligence enrichment:",
      error instanceof Error ? error.message : error
    );
    return data;
  }
  console.log({ hasMarketPerceptionAccess });

  // MOCKED -- LATER IWOULD DEPEND ON THE market_perception FEATURE
  // if (!hasMarketPerceptionAccess) {
  //   return data;
  // }

  // periodDays is intentionally NOT passed to MPI. GET /mpi/summary has no
  // period parameter, so changing Market Intelligence from 30 to 90 days does
  // not redefine the Market Perception Index.
  const competitors = await Promise.all(
    data.competitors.map((competitor) =>
      enrichMarketPerception(competitor, authorization)
    )
  );
  console.log({ competitors });

  return {
    ...data,
    competitors
  };
};

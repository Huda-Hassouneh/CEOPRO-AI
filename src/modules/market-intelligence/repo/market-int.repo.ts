import { prisma } from "../../../config/database.js";

const parseLocalized = (json: any, fallback: string = "Unknown") => {
  if (typeof json === "object" && json !== null) {
    return {
      en: json.en || fallback,

      ar: json.ar || fallback
    };
  }

  return {
    en: String(json || fallback),

    ar: String(json || fallback)
  };
};

export function localize(value: any, locale: any) {
  if (value && typeof value === "object")
    return value[locale] || value.en || Object.values(value)[0];

  return value;
}

const clamp = (value: number, min: number, max: number) =>
  Math.max(min, Math.min(max, value));

const getSegment = (category: any) => {
  const localized = parseLocalized(category, "");

  const en = String(localized.en || "").trim();

  const ar = String(localized.ar || "").trim();

  const canonical = en || ar;

  if (!canonical) return null;

  return {
    key: canonical.toLowerCase(),

    label: {
      en: en || canonical,

      ar: ar || canonical
    }
  };
};

const normalizeMapTo10 = (values: Map<string, number>) => {
  const entries = [...values.entries()].filter(([, value]) =>
    Number.isFinite(value)
  );

  const result = new Map<string, number>();

  // With fewer than 2 comparable segments, relative demand

  // normalization is not meaningful.

  if (entries.length < 2) {
    return result;
  }

  const rawValues = entries.map(([, value]) => value);

  const min = Math.min(...rawValues);

  const max = Math.max(...rawValues);

  // All segments have the same demand, so demand does not

  // distinguish one segment from another.

  if (max === min) {
    return result;
  }

  for (const [key, value] of entries) {
    result.set(key, ((value - min) / (max - min)) * 10);
  }

  return result;
};

type CompetitorScoreRow = {
  global_competitor_id: string;
  composite_score: unknown;
  relevance_score: unknown;
  market_activity_score: unknown;
};

const toFiniteNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) return null;

  const number = Number(value);

  return Number.isFinite(number) ? number : null;
};

const calculatePricingScore = (
  ownPrice: number | null,

  competitorPrice: number | null
): number | null => {
  if (
    ownPrice === null ||
    competitorPrice === null ||
    ownPrice <= 0 ||
    competitorPrice <= 0
  ) {
    return null;
  }

  return clamp(10 - Math.abs(1 - ownPrice / competitorPrice) * 10, 0, 10);
};

const average = (values: number[]): number | null =>
  values.length > 0
    ? values.reduce((sum, value) => sum + value, 0) / values.length
    : null;

export const getMarketIntelligence = async (
  tenant_id: string,

  productId?: string,

  periodDays: number = 30
) => {
  // ============================================================

  // 1. PRODUCTS

  // ============================================================

  const rawProducts = await prisma.products.findMany({
    where: {
      tenant_id,

      deleted_at: null
    },

    select: {
      product_id: true,

      product_name: true,

      category: true,

      currency: true,

      current_price: true
    }
  });

  if (rawProducts.length === 0) {
    return null;
  }

  const products = rawProducts.map((p) => ({
    id: p.product_id,

    name: parseLocalized(p.product_name),

    currency: p.currency
  }));

  const selectedProductRaw = productId
    ? rawProducts.find((p) => p.product_id === productId) || rawProducts[0]
    : rawProducts[0];

  const actualProductId = selectedProductRaw.product_id;

  const selectedProduct = products.find((p) => p.id === actualProductId);

  const currentPrice = toFiniteNumber(selectedProductRaw.current_price);

  const now = new Date();

  const periodStart = new Date(
    now.getTime() - periodDays * 24 * 60 * 60 * 1000
  );

  // ============================================================

  // 2. REAL COMPETITOR MAPPINGS + REAL SCRAPED PRICES

  // ============================================================

  const mappings = await prisma.competitor_product_mappings.findMany({
    where: {
      tenant_id,

      product_id: actualProductId,

      is_active: true,

      tenant_competitors: { is_tracked: true }
    },

    include: {
      tenant_competitors: {
        include: {
          global_competitors: true
        }
      },

      competitor_prices: {
        where: {
          is_available: true,

          is_exact_data: true,

          source_status: "ALLOWED",

          currency: selectedProductRaw.currency,

          observed_at: { gte: periodStart, lte: now }
        },

        orderBy: {
          observed_at: "desc"
        },

        take: 2
      }
    }
  });

  // ============================================================

  // 3. LATEST REAL COMPOSITE SCORE SNAPSHOTS

  //

  // The AI/collection pipeline stores competitor composite scores in

  // competitor_score_snapshots on a 0-100 scale. Prisma does not need

  // a generated model here because this table is read safely via

  // parameterized $queryRaw. Only the latest snapshot per competitor

  // mapped to the selected product is used.

  // ============================================================

  const latestCompetitorScores = await prisma.$queryRaw<CompetitorScoreRow[]>`
  SELECT DISTINCT ON (s.global_competitor_id)
    s.global_competitor_id,
    s.composite_score,
    s.relevance_score,
    s.market_activity_score
  FROM competitor_score_snapshots s
  INNER JOIN competitor_product_mappings m
    ON m.tenant_id = s.tenant_id
    AND m.global_competitor_id = s.global_competitor_id
  WHERE s.tenant_id = ${tenant_id}::uuid
    AND m.product_id = ${actualProductId}::uuid
    AND m.is_active = TRUE
  ORDER BY
    s.global_competitor_id,
    s.calculated_at DESC,
    s.score_id DESC
`;
  const marketActivityScoreByCompetitorId = new Map<string, number | null>(
    latestCompetitorScores.map((row) => [
      row.global_competitor_id,
      toFiniteNumber(row.market_activity_score)
    ])
  );
  const compositeScoreByCompetitorId = new Map<string, number | null>(
    latestCompetitorScores.map((row) => [
      row.global_competitor_id,

      toFiniteNumber(row.composite_score)
    ])
  );

  const relevanceScoreByCompetitorId = new Map<string, number | null>(
    latestCompetitorScores.map((row) => [
      row.global_competitor_id,

      toFiniteNumber(row.relevance_score)
    ])
  );

  const marketPrices: number[] = [];

  const recentPriceChanges: any[] = [];

  const competitorsData = mappings.map((mapping) => {
    const marketPresenceScore =
      marketActivityScoreByCompetitorId.get(mapping.global_competitor_id) ??
      null;
    const compositeScore =
      compositeScoreByCompetitorId.get(mapping.global_competitor_id) ?? null;

    const snapshotRelevance =
      relevanceScoreByCompetitorId.get(mapping.global_competitor_id) ?? null;

    const matchRate = toFiniteNumber(
      mapping.tenant_competitors.product_match_rate
    );

    const derivedRelevance =
      matchRate !== null && matchRate >= 0 && matchRate <= 1
        ? Number((matchRate * 100).toFixed(1))
        : null;

    const relevanceScore = snapshotRelevance ?? derivedRelevance;

    const competitorName =
      mapping.tenant_competitors.custom_alias ||
      mapping.tenant_competitors.global_competitors.competitor_name;

    const prices = mapping.competitor_prices;

    let latestScrapedPrice: number | null = null;

    if (prices.length > 0) {
      latestScrapedPrice = toFiniteNumber(prices[0].scraped_price);

      if (latestScrapedPrice !== null && latestScrapedPrice > 0) {
        marketPrices.push(latestScrapedPrice);
      }
    }

    // ==========================================================

    // REAL PRICE HISTORY

    // ==========================================================

    if (prices.length === 2) {
      const pCurrent = toFiniteNumber(prices[0].scraped_price);

      const pPrevious = toFiniteNumber(prices[1].scraped_price);

      if (pCurrent !== null && pPrevious !== null && pCurrent !== pPrevious) {
        recentPriceChanges.push({
          id: `change-${mapping.mapping_id}`,

          date: prices[0].observed_at.toISOString().split("T")[0],

          competitor: competitorName,

          previousPrice: pPrevious,

          newPrice: pCurrent,

          direction: pCurrent > pPrevious ? "increased" : "decreased",

          detectedAt: prices[0].observed_at.toISOString(),

          dataStatus: "verified",

          productId: actualProductId,

          productName: selectedProduct?.name
        });
      }
    }

    // ==========================================================

    // REAL DERIVED PRICING SCORE

    //

    // Based ONLY on:

    //   products.current_price

    //   competitor_prices.scraped_price

    //

    // No fabricated competitor values.

    // ==========================================================

    const pricingScore = calculatePricingScore(
      currentPrice,

      latestScrapedPrice
    );

    return {
      id: `${actualProductId}-${mapping.global_competitor_id}`,

      competitorId: mapping.global_competitor_id,

      competitorName,

      pricingScore:
        pricingScore !== null ? Number(pricingScore.toFixed(1)) : null,

      // Composite/relevance scores are DB-backed when the pipeline has

      // produced a snapshot. Market Presence has no agreed source here.

      // Market Perception is intentionally left null in the repo and is

      // enriched by the Market Intelligence service through the MPI module.

      compositeScore,

      relevanceScore,

      relevanceSource:
        snapshotRelevance !== null
          ? "snapshot"
          : derivedRelevance !== null
            ? "product_match_rate"
            : null,

      marketPresenceScore: marketPresenceScore,

      // Populated by the Market Intelligence service from the dedicated
      // MPI module. The repo stays DB-only.
      marketPerception: null,

      // Numeric 0-100 Market Perception Index from GET /mpi/summary.
      // Kept separate because the existing frontend uses marketPerception
      // as a qualitative positive/neutral/negative badge.
      marketPerceptionScore: null,

      dataStatus: latestScrapedPrice !== null ? "verified" : "unavailable",

      productId: actualProductId,

      productName: selectedProduct?.name
    };
  });

  const compositeScores = competitorsData

    .map((competitor) =>
      competitor.compositeScore !== null
        ? Number(competitor.compositeScore)
        : null
    )

    .filter(
      (score): score is number => score !== null && Number.isFinite(score)
    );

  const averageCompositeScore100 = average(compositeScores);

  // ============================================================

  // 4. REAL MARKET AGGREGATES

  // ============================================================

  const totalCompetitors = competitorsData.length;

  const pricedCompetitorCount = marketPrices.length;

  let marketMin: number | null = null;

  let marketMax: number | null = null;

  let marketAverage: number | null = null;

  let marketMedian: number | null = null;

  if (marketPrices.length > 0) {
    marketPrices.sort((a, b) => a - b);

    marketMin = marketPrices[0];

    marketMax = marketPrices[marketPrices.length - 1];

    marketAverage =
      marketPrices.reduce((sum, price) => sum + price, 0) / marketPrices.length;

    const middle = Math.floor(marketPrices.length / 2);

    marketMedian =
      marketPrices.length % 2 !== 0
        ? marketPrices[middle]
        : (marketPrices[middle - 1] + marketPrices[middle]) / 2;
  }

  // ============================================================

  // 5. DERIVED PRICING RECOMMENDATION

  //

  // Based on real competitor_prices.

  // This is an algorithmic recommendation, not fake market data.

  // ============================================================

  let action = "hold";

  let suggestedPrice = currentPrice;

  if (marketMedian !== null && currentPrice !== null) {
    if (currentPrice < marketMedian * 0.9) {
      action = "raise";

      suggestedPrice = Number((marketMedian * 0.95).toFixed(4));
    } else if (currentPrice > marketMedian * 1.1) {
      action = "reduce";

      suggestedPrice = Number((marketMedian * 1.05).toFixed(4));
    }
  }

  // ============================================================

  // 6. AVERAGE PRICING SCORE

  // ============================================================

  const pricingScores = competitorsData

    .map((competitor) =>
      competitor.pricingScore !== null ? Number(competitor.pricingScore) : null
    )

    .filter(
      (score): score is number => score !== null && Number.isFinite(score)
    );

  const averagePriceScore = average(pricingScores);

  // ============================================================

  // 7. TOP SEGMENT SCORE

  //

  // Segment = products.category

  //

  // Score:

  //   Demand    50%

  //   Sentiment 30%

  //   Pricing   20%

  //

  // Missing signals are excluded and remaining weights

  // are re-normalized automatically.

  // ============================================================

  type SegmentAccumulator = {
    label: {
      en: string;

      ar: string;
    };

    demand: number;

    demandCount: number;

    sentimentSum: number;

    sentimentCount: number;

    pricingSum: number;

    pricingCount: number;
  };

  const productIds = rawProducts.map((product) => product.product_id);

  const segmentByProductId = new Map<
    string,
    {
      key: string;

      label: {
        en: string;

        ar: string;
      };
    }
  >();

  const segments = new Map<string, SegmentAccumulator>();

  for (const product of rawProducts) {
    const segment = getSegment(product.category);

    // Products without a real category cannot participate

    // in segment scoring.

    if (!segment) continue;

    segmentByProductId.set(product.product_id, segment);

    if (!segments.has(segment.key)) {
      segments.set(segment.key, {
        label: segment.label,

        demand: 0,

        demandCount: 0,

        sentimentSum: 0,

        sentimentCount: 0,

        pricingSum: 0,

        pricingCount: 0
      });
    }
  }

  const previousPeriodStart = new Date(
    periodStart.getTime() - periodDays * 24 * 60 * 60 * 1000
  );

  const forecastWindowEnd = new Date(now);

  forecastWindowEnd.setDate(forecastWindowEnd.getDate() + periodDays);

  const [forecastRows, reviewRows, segmentPriceMappings] = await Promise.all([
    // ----------------------------------------------------------

    // DEMAND

    // ----------------------------------------------------------

    prisma.demand_forecasts.findMany({
      where: {
        tenant_id,

        product_id: {
          in: productIds
        },

        OR: [
          {
            forecast_start_date: { not: null, lte: forecastWindowEnd },

            forecast_end_date: {
              not: null,

              gte: new Date(now.toISOString().slice(0, 10))
            }
          },

          {
            forecast_target_date: {
              gte: new Date(now.toISOString().slice(0, 10)),

              lte: forecastWindowEnd
            }
          }
        ]
      },

      select: {
        product_id: true,

        expected_demand: true,

        forecast_target_date: true,

        forecast_start_date: true,

        forecast_end_date: true,

        created_at: true
      },

      orderBy: {
        created_at: "desc"
      }
    }),

    // ----------------------------------------------------------

    // SENTIMENT

    // ----------------------------------------------------------

    prisma.reviews.findMany({
      where: {
        tenant_id,

        product_id: {
          in: productIds
        },

        review_date: {
          gte: periodStart,

          lte: now
        },

        source_status: "ALLOWED",

        safety_status: "SAFE"
      },

      select: {
        product_id: true,

        sentiment_results: {
          select: {
            sentiment_score: true
          }
        }
      }
    }),

    // ----------------------------------------------------------

    // PRICING

    // ----------------------------------------------------------

    prisma.competitor_product_mappings.findMany({
      where: {
        tenant_id,

        product_id: {
          in: productIds
        },

        is_active: true,

        tenant_competitors: { is_tracked: true }
      },

      select: {
        product_id: true,

        competitor_prices: {
          where: {
            is_available: true,

            is_exact_data: true,

            source_status: "ALLOWED",

            observed_at: { gte: periodStart, lte: now }
          },

          orderBy: {
            observed_at: "desc"
          },

          take: 1,

          select: {
            scraped_price: true,

            currency: true
          }
        }
      }
    })
  ]);

  // ============================================================

  // DEMAND PER SEGMENT

  // ============================================================

  // Avoid double counting the same forecast window if multiple

  // model versions/runs exist. Because rows are ordered newest

  // first, the latest row wins.

  const seenForecastPeriods = new Set<string>();

  for (const forecast of forecastRows) {
    const segment = segmentByProductId.get(forecast.product_id);

    if (!segment) continue;

    const periodKey = [
      forecast.product_id,

      forecast.forecast_start_date?.toISOString() ?? "target",

      forecast.forecast_end_date?.toISOString() ??
        forecast.forecast_target_date?.toISOString() ??
        "unknown"
    ].join("|");

    if (seenForecastPeriods.has(periodKey)) continue;

    seenForecastPeriods.add(periodKey);

    const quantity = toFiniteNumber(forecast.expected_demand);

    if (quantity === null || quantity < 0) continue;

    const accumulator = segments.get(segment.key);

    if (!accumulator) continue;

    accumulator.demand += quantity;

    accumulator.demandCount += 1;
  }

  // ============================================================

  // SENTIMENT PER SEGMENT

  //

  // sentiment_score is expected around -1 .. +1.

  // ============================================================

  for (const review of reviewRows) {
    const segment = segmentByProductId.get(review.product_id as string);

    if (!segment || !review.sentiment_results) continue;

    const sentiment = toFiniteNumber(review.sentiment_results.sentiment_score);

    if (sentiment === null) continue;

    const accumulator = segments.get(segment.key);

    if (!accumulator) continue;

    accumulator.sentimentSum += clamp(sentiment, -1, 1);

    accumulator.sentimentCount += 1;
  }

  // ============================================================

  // PRICING PER SEGMENT

  //

  // Same pricing-score formula already used elsewhere in this

  // repository:

  //

  // 10 = very close to competitor price

  // 0  = very far from competitor price

  // ============================================================

  const currentPriceByProductId = new Map<string, number | null>(
    rawProducts.map(
      (product) =>
        [product.product_id, toFiniteNumber(product.current_price)] as [
          string,

          number | null
        ]
    )
  );

  const currencyByProductId = new Map(
    rawProducts.map((product) => [product.product_id, product.currency])
  );

  for (const mapping of segmentPriceMappings) {
    const segment = segmentByProductId.get(mapping.product_id);

    if (!segment) continue;

    const ownPrice = currentPriceByProductId.get(mapping.product_id);

    const competitorPrice =
      mapping.competitor_prices.length > 0 &&
      mapping.competitor_prices[0].currency ===
        currencyByProductId.get(mapping.product_id)
        ? toFiniteNumber(mapping.competitor_prices[0].scraped_price)
        : null;

    const pricingScore = calculatePricingScore(
      ownPrice ?? null,

      competitorPrice
    );

    if (pricingScore === null) continue;

    const accumulator = segments.get(segment.key);

    if (!accumulator) continue;

    accumulator.pricingSum += pricingScore;

    accumulator.pricingCount += 1;
  }

  // ============================================================

  // NORMALIZE DEMAND TO 0 .. 10

  // ============================================================

  const rawDemandBySegment = new Map<string, number>();

  for (const [key, segment] of segments) {
    if (segment.demandCount > 0) {
      rawDemandBySegment.set(key, segment.demand);
    }
  }

  const normalizedDemand = normalizeMapTo10(rawDemandBySegment);

  // ============================================================

  // FINAL SEGMENT SCORES

  // ============================================================

  const segmentScores: Array<{
    segment: {
      en: string;

      ar: string;
    };

    score: number;

    components: {
      demand: number | null;

      sentiment: number | null;

      pricing: number | null;
    };
  }> = [];

  for (const [key, segment] of segments) {
    const demandScore = normalizedDemand.get(key) ?? null;

    const sentimentScore =
      segment.sentimentCount > 0
        ? clamp(
            ((segment.sentimentSum / segment.sentimentCount + 1) / 2) * 10,

            0,

            10
          )
        : null;

    const pricingScore =
      segment.pricingCount > 0
        ? segment.pricingSum / segment.pricingCount
        : null;

    let weightedTotal = 0;

    let availableWeight = 0;

    if (demandScore !== null) {
      weightedTotal += demandScore * 0.5;

      availableWeight += 0.5;
    }

    if (sentimentScore !== null) {
      weightedTotal += sentimentScore * 0.3;

      availableWeight += 0.3;
    }

    if (pricingScore !== null) {
      weightedTotal += pricingScore * 0.2;

      availableWeight += 0.2;
    }

    // Nothing real exists for this segment.

    if (availableWeight === 0) continue;

    // Re-normalizes weights when one of the signals is missing.

    const score = weightedTotal / availableWeight;

    segmentScores.push({
      segment: segment.label,

      score,

      components: {
        demand: demandScore,

        sentiment: sentimentScore,

        pricing: pricingScore
      }
    });
  }

  segmentScores.sort((a, b) => {
    if (b.score !== a.score) {
      return b.score - a.score;
    }

    // deterministic tie breaker

    return a.segment.en.localeCompare(b.segment.en);
  });

  const topSegment = segmentScores[0] ?? null;

  const topSegmentScore =
    topSegment !== null ? Number(topSegment.score.toFixed(1)) : null;

  // Only compare complete, equally sized windows. A missing prior window

  // cannot establish a trend.

  const [sales, selectedReviews, activity] = await Promise.all([
    prisma.transactions.findMany({
      where: {
        tenant_id,

        product_id: { in: productIds },

        transaction_date: { gte: previousPeriodStart, lte: now }
      },

      select: { product_id: true, quantity_sold: true, transaction_date: true }
    }),

    prisma.reviews.findMany({
      where: {
        tenant_id,

        product_id: actualProductId,

        review_date: { gte: periodStart, lte: now },

        source_status: "ALLOWED",

        safety_status: "SAFE"
      },

      select: {
        review_date: true,

        sentiment_results: { select: { sentiment_score: true } }
      }
    }),

    mappings.length
      ? prisma.market_events.findMany({
          where: {
            tenant_id,

            mapping_id: { in: mappings.map((mapping) => mapping.mapping_id) },

            occurred_at: { gte: previousPeriodStart, lte: now }
          },

          select: { occurred_at: true }
        })
      : Promise.resolve([])
  ]);

  type Driver = {
    id: string;

    direction: "positive" | "negative";

    type: "demand" | "sentiment" | "pricing" | "activity";

    text: { en: string; ar: string };
  };

  const drivers: Driver[] = [];

  const evidenceDates: Date[] = [];

  const selectedSales = sales.filter(
    (sale) => sale.product_id === actualProductId
  );

  const previousSales = selectedSales.filter(
    (sale) => sale.transaction_date < periodStart
  );

  const currentSales = selectedSales.filter(
    (sale) => sale.transaction_date >= periodStart
  );

  if (previousSales.length && currentSales.length) {
    const previousUnits = previousSales.reduce(
      (sum, sale) => sum + sale.quantity_sold,

      0
    );

    const currentUnits = currentSales.reduce(
      (sum, sale) => sum + sale.quantity_sold,

      0
    );

    if (currentUnits !== previousUnits) {
      const rising = currentUnits > previousUnits;

      drivers.push({
        id: "sales",

        direction: rising ? "positive" : "negative",

        type: "demand",

        text: {
          en: `Recorded sales ${rising ? "rose" : "fell"} from ${previousUnits} to ${currentUnits} units compared with the preceding ${periodDays} days.`,

          ar: `المبيعات المسجلة ${rising ? "ارتفعت" : "انخفضت"} من ${previousUnits} إلى ${currentUnits} وحدة مقارنة بفترة ${periodDays} يوماً السابقة.`
        }
      });

      evidenceDates.push(...currentSales.map((sale) => sale.transaction_date));
    }
  }

  const scoredReviews = selectedReviews.filter(
    (review) =>
      toFiniteNumber(review.sentiment_results?.sentiment_score) !== null
  );

  const meanSentiment = average(
    scoredReviews.map((review) =>
      Number(review.sentiment_results!.sentiment_score)
    )
  );

  const sentiment =
    meanSentiment === null
      ? null
      : meanSentiment > 0.1
        ? "positive"
        : meanSentiment < -0.1
          ? "negative"
          : "neutral";

  const sentimentSummary =
    sentiment === null
      ? null
      : {
          en: `${scoredReviews.length} analyzed product review${scoredReviews.length === 1 ? "" : "s"} in the last ${periodDays} days had ${sentiment} average sentiment.`,

          ar: `أظهر متوسط مشاعر ${scoredReviews.length} من مراجعات المنتج المحللة خلال آخر ${periodDays} يوماً تقييماً ${sentiment === "positive" ? "إيجابياً" : sentiment === "negative" ? "سلبياً" : "محايداً"}.`
        };

  if (sentiment && sentiment !== "neutral" && sentimentSummary) {
    drivers.push({
      id: "reviews",

      direction: sentiment === "positive" ? "positive" : "negative",

      type: "sentiment",

      text: sentimentSummary
    });

    evidenceDates.push(...scoredReviews.map((review) => review.review_date));
  }

  const priceDecreases = mappings.filter((mapping) => {
    const [latest, previous] = mapping.competitor_prices;

    return (
      latest &&
      previous &&
      latest.observed_at >= periodStart &&
      latest.observed_at <= now &&
      latest.currency === previous.currency &&
      latest.source_status === "ALLOWED" &&
      previous.source_status === "ALLOWED" &&
      latest.is_exact_data &&
      previous.is_exact_data &&
      Number(latest.scraped_price) < Number(previous.scraped_price)
    );
  });

  if (priceDecreases.length) {
    drivers.push({
      id: "price-decreases",

      direction: "negative",

      type: "pricing",

      text: {
        en: `Recorded prices fell for ${priceDecreases.length} mapped competitor product${priceDecreases.length === 1 ? "" : "s"} during this period.`,

        ar: `انخفضت الأسعار المسجلة لدى ${priceDecreases.length} من منتجات المنافسين المرتبطة خلال هذه الفترة.`
      }
    });

    evidenceDates.push(
      ...priceDecreases.map(
        (mapping) => mapping.competitor_prices[0].observed_at
      )
    );
  }

  const previousEvents = activity.filter(
    (event) => event.occurred_at < periodStart
  ).length;

  const currentEvents = activity.filter(
    (event) => event.occurred_at >= periodStart
  );

  if (previousEvents && currentEvents.length > previousEvents) {
    drivers.push({
      id: "activity",

      direction: "negative",

      type: "activity",

      text: {
        en: `Recorded competitor events rose from ${previousEvents} to ${currentEvents.length} compared with the preceding ${periodDays} days.`,

        ar: `ارتفعت أحداث المنافسين المسجلة من ${previousEvents} إلى ${currentEvents.length} مقارنة بفترة ${periodDays} يوماً السابقة.`
      }
    });

    evidenceDates.push(...currentEvents.map((event) => event.occurred_at));
  }

  const aiMarketIntelligence = drivers.length
    ? {
        insight: {
          en: drivers.map((driver) => driver.text.en).join(" "),

          ar: drivers.map((driver) => driver.text.ar).join(" ")
        },

        drivers,

        sentiment,

        sentimentSummary,

        generatedAt: new Date(
          Math.max(...evidenceDates.map((date) => date.getTime()))
        ).toISOString(),

        confidence: null,

        dataStatus: "derived"
      }
    : null;

  const expansionOpportunities = rawProducts

    .filter((product) => product.product_id !== actualProductId)

    .map((product) => {
      const productSales = sales.filter(
        (sale) => sale.product_id === product.product_id
      );

      const prior = productSales.filter(
        (sale) => sale.transaction_date < periodStart
      );

      const recent = productSales.filter(
        (sale) => sale.transaction_date >= periodStart
      );

      if (!prior.length || !recent.length) return null;

      const priorUnits = prior.reduce(
        (sum, sale) => sum + sale.quantity_sold,

        0
      );

      const recentUnits = recent.reduce(
        (sum, sale) => sum + sale.quantity_sold,

        0
      );

      if (priorUnits <= 0 || recentUnits <= priorUnits) return null;

      const growthPercent = Math.round(
        ((recentUnits - priorUnits) / priorUnits) * 100
      );

      return {
        id: product.product_id,

        productName: parseLocalized(product.product_name),

        growthPercent,

        recentUnits,

        priorUnits,

        explanation: {
          en: `Recorded unit sales rose from ${priorUnits} to ${recentUnits} compared with the preceding ${periodDays} days. This is a signal to investigate, not a market demand forecast.`,

          ar: `ارتفعت المبيعات المسجلة من ${priorUnits} إلى ${recentUnits} وحدة مقارنة بفترة ${periodDays} يوماً السابقة. هذه إشارة تستدعي الدراسة وليست توقعاً لطلب السوق.`
        },

        dataStatus: "derived"
      };
    })

    .filter(
      (opportunity): opportunity is NonNullable<typeof opportunity> =>
        opportunity !== null
    )

    .sort(
      (a, b) => b.growthPercent - a.growthPercent || a.id.localeCompare(b.id)
    )

    .slice(0, 3);

  // ============================================================

  // 8. RESPONSE

  //

  // Existing property names are preserved.

  // ============================================================

  return {
    companyId: tenant_id,

    period: {
      days: periodDays
    },

    availablePeriods: [30, 90],

    products,

    selectedProduct,

    // ==========================================================

    // METRICS

    // ==========================================================

    metrics: [
      {
        id: "totalCompetitors",

        value: totalCompetitors,

        format: "number",

        icon: "users",

        dataStatus: "verified"
      },

      {
        id: "averagePriceScore",

        value:
          averagePriceScore !== null
            ? Number(averagePriceScore.toFixed(1))
            : null,

        format: "score10",

        icon: "price",

        dataStatus: averagePriceScore !== null ? "derived" : "unavailable"
      },

      // Derived intelligence KPIs

      {
        id: "averageCompositeScore",

        value:
          averageCompositeScore100 !== null
            ? Number(averageCompositeScore100.toFixed(1))
            : null,

        format: "score100",

        icon: "composite",

        dataStatus:
          averageCompositeScore100 !== null ? "derived" : "unavailable"
      },

      {
        id: "topSegmentScore",

        value: topSegmentScore,

        format: "score10",

        icon: "presence",

        dataStatus: topSegment ? "derived" : "unavailable",

        // Extra explanation data.

        // Existing frontend can ignore these until you want to show them.

        segment: topSegment?.segment ?? null,

        components: topSegment?.components ?? null
      }
    ],

    // ==========================================================

    // Derived solely from dated, tenant-scoped records above.

    // ==========================================================

    aiMarketIntelligence,

    expansionOpportunities,

    // ==========================================================

    // COMPETITORS

    // ==========================================================

    competitors: competitorsData,

    // ==========================================================

    // PRICING RECOMMENDATIONS

    // ==========================================================

    pricingRecommendations:
      pricedCompetitorCount > 0 && currentPrice !== null
        ? [
            {
              id: `price-rec-${actualProductId}`,

              currentPrice,

              action,

              suggestedPrice,

              marketMin,

              marketMax,

              marketAverage:
                marketAverage === null
                  ? null
                  : Number(marketAverage.toFixed(4)),

              marketMedian,

              matchedCompetitors: pricedCompetitorCount,

              explanation: {
                en:
                  pricedCompetitorCount > 0
                    ? `Algorithm derived from ${pricedCompetitorCount} tracked competitors with recorded prices.`
                    : "No competitor price data is currently available.",

                ar:
                  pricedCompetitorCount > 0
                    ? `الخوارزمية مستمدة من ${pricedCompetitorCount} منافسين متابعين لديهم أسعار مسجلة.`
                    : "لا تتوفر حاليًا بيانات أسعار للمنافسين."
              },

              dataStatus: pricedCompetitorCount > 0 ? "derived" : "unavailable",

              productId: actualProductId,

              productName: selectedProduct?.name
            }
          ]
        : [],

    // ==========================================================

    // REAL PRICE HISTORY

    // ==========================================================

    recentPriceChanges
  };
};

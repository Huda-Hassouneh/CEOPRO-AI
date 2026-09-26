import { prisma } from "../../config/database.js";

export const getCompetitorLeaderboard = async (tenant_id: string) => {
  // 1. Fetch all tracked competitors with their product mappings and latest prices[cite: 9]
  const competitors = await prisma.tenant_competitors.findMany({
    where: { tenant_id, is_tracked: true },
    include: {
      global_competitors: true,
      competitor_product_mappings: {
        where: { is_active: true },
        include: {
          products: { select: { current_price: true } },
          competitor_prices: {
            where: { is_available: true },
            orderBy: { observed_at: "desc" },
            take: 1 // Only need the most recent scraped price[cite: 9]
          }
        }
      }
    }
  });

  // 2. Transform the nested database relations into a flat leaderboard array
  const leaderboard = competitors.map((competitor) => {
    let totalScore = 0;
    let validComparisons = 0;

    // Calculate a Price Competitiveness Score based on the gap between their price and our price
    for (const mapping of competitor.competitor_product_mappings) {
      if (mapping.competitor_prices.length > 0 && mapping.products) {
        const theirPrice = Number(mapping.competitor_prices[0].scraped_price);
        const ourPrice = Number(mapping.products.current_price);

        if (ourPrice > 0) {
          // If they charge 90 and we charge 100, their index is 90 (they are cheaper/higher threat)
          const priceIndex = (theirPrice / ourPrice) * 100;
          totalScore += priceIndex;
          validComparisons += 1;
        }
      }
    }

    const averagePriceScore =
      validComparisons > 0 ? totalScore / validComparisons : 0;

    return {
      id: competitor.global_competitor_id,
      name:
        competitor.custom_alias ||
        competitor.global_competitors.competitor_name,
      domain:
        competitor.global_competitors.website_url?.replace(
          /^https?:\/\//,
          ""
        ) || "N/A",
      mappedProductsCount: validComparisons,
      priceScore: averagePriceScore
    };
  });

  // 3. Sort competitors by their price threat level (lowest prices compared to ours rank first)
  leaderboard.sort((a, b) => a.priceScore - b.priceScore);

  // 4. Assign a strict rank based on the sorted array
  return leaderboard.map((comp, index) => ({
    ...comp,
    rank: index + 1
  }));
};

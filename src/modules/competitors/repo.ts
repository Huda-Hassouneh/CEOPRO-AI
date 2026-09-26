import { prisma } from "../../config/database.js";

// Helper to safely parse localized JSON from Prisma
const parseLocalized = (json: any, fallback: string = "Unknown") => {
  if (typeof json === "object" && json !== null) {
    return { en: json.en || fallback, ar: json.ar || fallback };
  }
  return { en: String(json || fallback), ar: String(json || fallback) };
};

export const getCompetitorsList = async (tenant_id: string) => {
  // Fetch tenant competitors and join global info[cite: 1]
  const competitors = await prisma.tenant_competitors.findMany({
    where: { tenant_id, is_tracked: true },
    include: { global_competitors: true },
    orderBy: { added_at: "desc" }
  });

  return competitors.map((tc) => ({
    id: tc.global_competitor_id,
    name: tc.custom_alias || tc.global_competitors.competitor_name,
    website: tc.global_competitors.website_url || "",
    industry: tc.global_competitors.industry_sector || "Uncategorized",
    isTracked: tc.is_tracked,
    addedAt: tc.added_at
  }));
};

export const getCompetitorProfile = async (
  tenant_id: string,
  competitorId: string
) => {
  const competitor = await prisma.tenant_competitors.findUnique({
    where: {
      tenant_id_global_competitor_id: {
        tenant_id,
        global_competitor_id: competitorId
      }
    },
    include: { global_competitors: true }
  });

  if (!competitor) return null;

  // Fetch all products mapped to this competitor with price history[cite: 1]
  const mappings = await prisma.competitor_product_mappings.findMany({
    where: { tenant_id, global_competitor_id: competitorId, is_active: true },
    include: {
      products: true,
      competitor_prices: {
        where: { is_available: true },
        orderBy: { observed_at: "desc" }
      }
    }
  });

  const mappedProducts = [];
  const activityTimeline = [];

  for (const mapping of mappings) {
    const productName = parseLocalized(mapping.products.product_name);
    const prices = mapping.competitor_prices;

    // Build the mapped products list
    if (prices.length > 0) {
      mappedProducts.push({
        id: mapping.product_id,
        name: productName,
        ourPrice: Number(mapping.products.current_price),
        competitorPrice: Number(prices[0].scraped_price),
        currency: prices[0].currency,
        url: mapping.competitor_product_url || null,
        sku: mapping.competitor_product_sku || null,
        lastUpdated: prices[0].observed_at
      });
    }

    // Generate real activity timeline from actual price changes[cite: 1]
    for (let i = 0; i < prices.length - 1; i++) {
      const current = Number(prices[i].scraped_price);
      const previous = Number(prices[i + 1].scraped_price);

      if (current !== previous) {
        activityTimeline.push({
          id: prices[i].competitor_price_id,
          type: "PRICE_CHANGE",
          productName,
          previousPrice: previous,
          newPrice: current,
          currency: prices[i].currency,
          date: prices[i].observed_at
        });
      }
    }
  }

  // Sort activity timeline strictly by date (newest first)
  activityTimeline.sort((a, b) => b.date.getTime() - a.date.getTime());

  return {
    id: competitor.global_competitor_id,
    name:
      competitor.custom_alias || competitor.global_competitors.competitor_name,
    website: competitor.global_competitors.website_url,
    industry: competitor.global_competitors.industry_sector,
    addedAt: competitor.added_at,

    // Database-backed Data
    mappedProducts,
    activity: activityTimeline,

    // Schema unsupported fields - strictly emptied to prevent UI crashes while adhering to rules
    metrics: [],
    strengths: [],
    weaknesses: [],
    presence: { current: [], previous: [] }
  };
};

export const createCompetitor = async (
  tenant_id: string,
  data: { name: string; website?: string; industry?: string }
) => {
  // 1. Find or create in the global pool (idempotent)[cite: 1]
  let globalComp = await prisma.global_competitors.findFirst({
    where: { competitor_name: data.name }
  });

  if (!globalComp) {
    globalComp = await prisma.global_competitors.create({
      data: {
        competitor_name: data.name,
        website_url: data.website || null,
        industry_sector: data.industry || null,
        visibility: "GLOBAL",
        added_by_tenant_id: tenant_id
      }
    });
  }

  // 2. Link to tenant[cite: 1]
  const tenantComp = await prisma.tenant_competitors.upsert({
    where: {
      tenant_id_global_competitor_id: {
        tenant_id,
        global_competitor_id: globalComp.global_competitor_id
      }
    },
    update: { is_tracked: true },
    create: {
      tenant_id,
      global_competitor_id: globalComp.global_competitor_id,
      is_tracked: true
    }
  });

  return {
    id: globalComp.global_competitor_id,
    name: globalComp.competitor_name,
    isTracked: tenantComp.is_tracked
  };
};

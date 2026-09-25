import "dotenv/config";
import { prisma } from "../src/config/database.js";
import {
  CANONICAL_FEATURES,
  CANONICAL_FEATURE_CODES,
  canonicalizeFeatureCode
} from "../src/modules/features/catalog.js";

const EXPECTED_FEATURE_COUNT = 21;

function assertSafeEnvironment() {
  if (!process.env.DATABASE_URL) {
    throw new Error("DATABASE_URL is required to bootstrap features.");
  }

  if (
    process.env.NODE_ENV === "production" &&
    process.env.ALLOW_PRODUCTION_FEATURE_BOOTSTRAP !== "true"
  ) {
    throw new Error(
      "Refusing to rebuild the production feature catalog. Set ALLOW_PRODUCTION_FEATURE_BOOTSTRAP=true only when this destructive action is intentional."
    );
  }

  if (CANONICAL_FEATURES.length !== EXPECTED_FEATURE_COUNT) {
    throw new Error(
      `Canonical feature catalog must contain exactly ${EXPECTED_FEATURE_COUNT} definitions.`
    );
  }

  const codes = new Set(CANONICAL_FEATURE_CODES);
  if (codes.size !== CANONICAL_FEATURES.length) {
    throw new Error("Canonical feature catalog contains duplicate feature codes.");
  }
}

async function main() {
  assertSafeEnvironment();

  const summary = await prisma.$transaction(async (tx) => {
    const existingFeatures = await tx.feature.findMany({
      select: { id: true, code: true }
    });
    const codeById = new Map(existingFeatures.map((feature) => [feature.id, feature.code]));

    const [planLinks, usageRows, quoteFeatures, vendorRates, planCount] =
      await Promise.all([
        tx.planFeature.findMany(),
        tx.subscriptionUsage.findMany(),
        tx.customPlanQuoteFeature.findMany(),
        tx.vendorRate.findMany({ where: { featureId: { not: null } } }),
        tx.plan.count()
      ]);

    const mapCode = (featureId: string) => {
      const oldCode = codeById.get(featureId);
      return oldCode ? canonicalizeFeatureCode(oldCode) : null;
    };

    const planSnapshots = planLinks
      .map((row) => ({ ...row, code: mapCode(row.feature_id) }))
      .filter((row) => row.code && CANONICAL_FEATURE_CODES.includes(row.code as any));

    const meteredSumCodes = new Set(
      CANONICAL_FEATURES
        .filter((feature) => feature.type === "limit" && feature.aggregationType === "sum")
        .map((feature) => feature.code)
    );

    const usageSnapshots = usageRows
      .map((row) => ({ ...row, code: mapCode(row.feature_id) }))
      .filter((row) => row.code && meteredSumCodes.has(row.code as any));

    const quoteSnapshots = quoteFeatures
      .map((row) => ({ ...row, code: mapCode(row.featureId) }))
      .filter((row) => row.code && CANONICAL_FEATURE_CODES.includes(row.code as any));

    const vendorSnapshots = vendorRates
      .map((row) => ({ ...row, code: row.featureId ? mapCode(row.featureId) : null }))
      .filter((row) => row.code && CANONICAL_FEATURE_CODES.includes(row.code as any));

    if (vendorRates.length) {
      await tx.vendorRate.updateMany({
        where: { featureId: { not: null } },
        data: { featureId: null }
      });
    }

    await tx.customPlanQuoteFeature.deleteMany();
    await tx.subscriptionUsage.deleteMany();
    await tx.planFeature.deleteMany();
    const deletedFeatures = await tx.feature.deleteMany();

    await tx.feature.createMany({ data: CANONICAL_FEATURES as any });

    const createdFeatures = await tx.feature.findMany({
      select: { id: true, code: true }
    });
    const idByCode = new Map(createdFeatures.map((feature) => [feature.code, feature.id]));

    const uniquePlanLinks = new Map<string, (typeof planSnapshots)[number]>();
    for (const snapshot of planSnapshots) {
      const key = `${snapshot.plan_id}:${snapshot.code}`;
      const existing = uniquePlanLinks.get(key);
      // When legacy and canonical codes collapse to the same entitlement,
      // preserve unlimited rather than accidentally narrowing an existing plan.
      if (!existing || (snapshot.limit_value === null && existing.limit_value !== null)) {
        uniquePlanLinks.set(key, snapshot);
      }
    }

    for (const snapshot of uniquePlanLinks.values()) {
      const featureId = idByCode.get(snapshot.code!);
      if (!featureId) continue;
      await tx.planFeature.create({
        data: {
          plan_id: snapshot.plan_id,
          feature_id: featureId,
          limit_value: snapshot.limit_value
        }
      });
    }

    for (const snapshot of usageSnapshots) {
      const featureId = idByCode.get(snapshot.code!);
      if (!featureId) continue;
      await tx.subscriptionUsage.upsert({
        where: {
          subscription_id_feature_id_period_start: {
            subscription_id: snapshot.subscription_id,
            feature_id: featureId,
            period_start: snapshot.period_start
          }
        },
        update: {
          current_usage: snapshot.current_usage,
          period_end: snapshot.period_end
        },
        create: {
          subscription_id: snapshot.subscription_id,
          feature_id: featureId,
          current_usage: snapshot.current_usage,
          period_start: snapshot.period_start,
          period_end: snapshot.period_end
        }
      });
    }

    const uniqueQuoteLinks = new Map<string, (typeof quoteSnapshots)[number]>();
    for (const snapshot of quoteSnapshots) {
      uniqueQuoteLinks.set(`${snapshot.quoteId}:${snapshot.code}`, snapshot);
    }
    for (const snapshot of uniqueQuoteLinks.values()) {
      const featureId = idByCode.get(snapshot.code!);
      if (!featureId) continue;
      await tx.customPlanQuoteFeature.create({
        data: {
          id: snapshot.id,
          quoteId: snapshot.quoteId,
          featureId,
          limitValue: snapshot.limitValue,
          estimatedUsage: snapshot.estimatedUsage,
          metadata: snapshot.metadata ?? undefined,
          createdAt: snapshot.createdAt,
          updatedAt: snapshot.updatedAt
        }
      });
    }

    for (const snapshot of vendorSnapshots) {
      const featureId = idByCode.get(snapshot.code!);
      if (!featureId) continue;
      await tx.vendorRate.update({
        where: { id: snapshot.id },
        data: { featureId }
      });
    }

    const finalFeatures = await tx.feature.findMany({
      select: { code: true },
      orderBy: { code: "asc" }
    });
    if (finalFeatures.length !== EXPECTED_FEATURE_COUNT) {
      throw new Error(
        `Feature bootstrap verification failed: expected ${EXPECTED_FEATURE_COUNT}, found ${finalFeatures.length}.`
      );
    }

    const finalCodes = new Set(finalFeatures.map((feature) => feature.code));
    for (const code of CANONICAL_FEATURE_CODES) {
      if (!finalCodes.has(code)) {
        throw new Error(`Feature bootstrap verification failed: missing ${code}.`);
      }
    }

    return {
      deletedFeatures: deletedFeatures.count,
      createdFeatures: finalFeatures.length,
      restoredPlanLinks: uniquePlanLinks.size,
      restoredUsageRows: usageSnapshots.length,
      restoredQuoteFeatures: uniqueQuoteLinks.size,
      restoredVendorRates: vendorSnapshots.length,
      removedObsoleteMappings: planLinks.length - uniquePlanLinks.size,
      plansChecked: planCount
    };
  });

  console.log("");
  console.log("========================================");
  console.log("Feature bootstrap completed");
  console.log("========================================");
  console.log(`Deleted feature definitions: ${summary.deletedFeatures}`);
  console.log(`Created canonical features: ${summary.createdFeatures}`);
  console.log(`Restored plan-feature links: ${summary.restoredPlanLinks}`);
  console.log(`Restored usage rows: ${summary.restoredUsageRows}`);
  console.log(`Restored custom quote features: ${summary.restoredQuoteFeatures}`);
  console.log(`Restored vendor rates: ${summary.restoredVendorRates}`);
  console.log(`Removed obsolete mappings: ${summary.removedObsoleteMappings}`);
  console.log(`Plans checked: ${summary.plansChecked}`);
  console.log("========================================");
}

main()
  .catch((error) => {
    console.error("");
    console.error("Feature bootstrap failed:");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await prisma.$disconnect();
  });

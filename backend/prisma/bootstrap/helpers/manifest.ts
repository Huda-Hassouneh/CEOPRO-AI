import { prisma } from "../../../src/config/database.js";
import {
  CANONICAL_FEATURES,
  CANONICAL_FEATURE_CODES
} from "../../../src/modules/features/types/feature.catalog.js";
import { validatePlanOptions } from "../../../src/modules/subscription/service/plan-pricing.js";
import { PRODUCTION_PLANS } from "../../../src/config/production-plans.js";
import { info, logStep, success } from "./logs.js";
import type { BootstrapExecutionMode } from "./environment.js";
function canonicalFeature(code: string): any {
  const definition = (CANONICAL_FEATURES as readonly any[]).find(
    (item) => item.code === code
  );
  if (!definition) {
    throw new Error(
      `Canonical feature '${code}' is missing from source catalog.`
    );
  }
  return definition;
}
export function assertManifest(): void {
  if (PRODUCTION_PLANS.length !== 3) {
    throw new Error(
      "Production catalog must contain exactly Starter, Growth, and Enterprise."
    );
  }
  const expected = ["Starter", "Growth", "Enterprise"];
  if (
    PRODUCTION_PLANS.map((plan) => plan.name).join("|") !== expected.join("|")
  ) {
    throw new Error(
      "Production catalog tier order must be Starter → Growth → Enterprise."
    );
  }
  const names = new Set<string>();
  const tierLevels = new Set<number>();
  for (const plan of PRODUCTION_PLANS) {
    if (names.has(plan.name)) {
      throw new Error(`Duplicate production plan name: ${plan.name}`);
    }
    if (tierLevels.has(plan.tierLevel)) {
      throw new Error(`Duplicate tier level: ${plan.tierLevel}`);
    }
    names.add(plan.name);
    tierLevels.add(plan.tierLevel);
    if (!Number.isFinite(plan.price) || plan.price <= 0) {
      throw new Error(`${plan.name} must have a positive finite price.`);
    }
    if (!/^[A-Z]{3}$/.test(plan.currency)) {
      throw new Error(`${plan.name} has an invalid currency.`);
    }
    const options = validatePlanOptions(
      [...plan.billingOptions],
      plan.price,
      plan.billingIntervalValue,
      plan.billingIntervalUnit,
      plan.currency
    );
    if (options.length !== plan.billingOptions.length) {
      throw new Error(`${plan.name} billing option validation failed.`);
    }
    const seenFeatures = new Set<string>();
    for (const entitlement of plan.features) {
      if (!CANONICAL_FEATURE_CODES.includes(entitlement.code as any)) {
        throw new Error(
          `${plan.name} references non-canonical feature '${entitlement.code}'.`
        );
      }
      const definition = canonicalFeature(entitlement.code);
      if (definition.type === "boolean" && entitlement.limitValue !== null) {
        throw new Error(
          `${plan.name}/${entitlement.code} is boolean and must not define a numeric limit.`
        );
      }
      if (definition.type === "limit" && entitlement.limitValue === null) {
        throw new Error(
          `${plan.name}/${entitlement.code} is a limited feature and must define a numeric limit.`
        );
      }
      if (seenFeatures.has(entitlement.code)) {
        throw new Error(
          `${plan.name} contains feature '${entitlement.code}' more than once.`
        );
      }
      seenFeatures.add(entitlement.code);
      if (
        entitlement.limitValue !== null &&
        (!Number.isInteger(entitlement.limitValue) ||
          entitlement.limitValue <= 0)
      ) {
        throw new Error(
          `${plan.name}/${entitlement.code} must have a positive integer limit.`
        );
      }
    }
    const competitorManagement = plan.features.find(
      (feature) => feature.code === "competitor_management"
    );
    const trackedCompetitors = plan.features.find(
      (feature) => feature.code === "tracked_competitors"
    );
    if (competitorManagement && !trackedCompetitors?.limitValue) {
      throw new Error(
        `${plan.name} enables competitor_management without tracked_competitors capacity.`
      );
    }
    if (competitorManagement) {
      const configuration = (competitorManagement.metadata as any)
        ?.configuration;
      if (
        !Number.isInteger(configuration?.monitoringFrequencyMinutes) ||
        configuration.monitoringFrequencyMinutes <= 0
      ) {
        throw new Error(
          `${plan.name}/competitor_management requires a positive monitoringFrequencyMinutes configuration.`
        );
      }
    }
    if (
      plan.features.some((feature) => feature.code === "data_integration") &&
      !plan.features.find(
        (feature) => feature.code === "connected_data_sources"
      )?.limitValue
    ) {
      throw new Error(
        `${plan.name} enables data_integration without connected_data_sources capacity.`
      );
    }
  }
}
export async function ensureManifestFeatures(
  mode: BootstrapExecutionMode
): Promise<void> {
  logStep("Reconciling canonical feature definitions used by production plans");
  // A clean production database needs the complete canonical feature registry,
  // not only the subset attached to the three public plans. Hidden/not-yet-
  // commercialized features may still be used by custom-plan/admin workflows.
  const requiredCodes = [...CANONICAL_FEATURE_CODES];
  for (const code of requiredCodes) {
    const definition = canonicalFeature(code);
    const existing = await prisma.feature.findUnique({ where: { code } });
    if (!existing) {
      if (mode.verifyOnly) {
        throw new Error(
          `Required feature '${code}' is missing from the database.`
        );
      }
      if (mode.dryRun) {
        info(`would create missing feature ${code}`);
        continue;
      }
      await prisma.feature.create({ data: definition });
      success(`created missing feature ${code}`);
      continue;
    }
    if (
      existing.type !== definition.type ||
      existing.aggregationType !== definition.aggregationType ||
      existing.resetCycle !== definition.resetCycle
    ) {
      throw new Error(
        `Feature '${code}' has a structural type/aggregation/reset mismatch. Refusing to silently change production entitlement semantics.`
      );
    }
    const desiredUnit = definition.unit ?? null;
    const desiredUnitAr = definition.unit_ar ?? null;
    const unitMismatch =
      existing.unit !== desiredUnit || existing.unit_ar !== desiredUnitAr;
    const knownRagCorrection =
      code === "rag_assistant" &&
      (existing.unit === "queries" || existing.unit === "tokens") &&
      (existing.unit_ar === "استفسار" || existing.unit_ar === "رمز");
    if (unitMismatch && !knownRagCorrection) {
      throw new Error(
        `Feature '${code}' unit differs from the canonical catalog (${existing.unit ?? "null"} → ${desiredUnit ?? "null"}). Review this commercial change explicitly.`
      );
    }
    const needsMetadataSync =
      existing.name !== definition.name ||
      existing.name_ar !== definition.name_ar ||
      existing.description !== (definition.description ?? null) ||
      existing.description_ar !== (definition.description_ar ?? null) ||
      unitMismatch;
    if (!needsMetadataSync) {
      success(`${code} already matches canonical definition`);
      continue;
    }
    if (mode.verifyOnly) {
      throw new Error(
        `Feature '${code}' metadata/unit does not match the canonical definition.`
      );
    }
    if (mode.dryRun) {
      info(`would reconcile feature metadata for ${code}`);
      continue;
    }
    await prisma.feature.update({
      where: { code },
      data: {
        name: definition.name,
        name_ar: definition.name_ar,
        description: definition.description ?? null,
        description_ar: definition.description_ar ?? null,
        unit: desiredUnit,
        unit_ar: desiredUnitAr
      }
    });
    success(
      code === "rag_assistant" && unitMismatch
        ? "rag_assistant corrected to token-based commercial/usage units"
        : `${code} metadata reconciled`
    );
  }
}

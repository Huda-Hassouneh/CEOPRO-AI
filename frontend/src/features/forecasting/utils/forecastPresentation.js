const coverageStates = new Set(["complete", "partial", "overlapping", "unavailable", "stale"]);
export function coveragePresentation(coverage, periodDays) {
  const status = coverageStates.has(coverage?.status) ? coverage.status : "unavailable";
  const total = Number.isInteger(coverage?.periodDays) && coverage.periodDays > 0 ? coverage.periodDays : periodDays;
  const covered = Number.isInteger(coverage?.coveredDays) ? Math.max(0, Math.min(total, coverage.coveredDays)) : 0;
  return { status, covered, total };
}
export function prepareForecastExport(data, inventoryAllowed = data?.featureAccess?.inventoryIntelligence === true) {
  if (!data) return data;
  return {
    ...data,
    featureAccess: { ...data.featureAccess, inventoryIntelligence: inventoryAllowed },
    recommendation: inventoryAllowed ? data.recommendation : null,
    recommendationStatus: inventoryAllowed ? data.recommendationStatus : null,
    forecasts: (data.forecasts ?? []).map((row) => ({ ...row,
      recommendedAction: inventoryAllowed ? row.recommendedAction : null,
      suggestedQuantity: inventoryAllowed ? row.suggestedQuantity : null,
      recommendation: inventoryAllowed ? row.recommendation : null,
      recommendationStatus: inventoryAllowed ? row.recommendationStatus : null
    }))
  };
}

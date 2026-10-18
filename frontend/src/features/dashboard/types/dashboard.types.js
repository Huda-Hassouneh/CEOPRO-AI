export const dashboardDataStatuses = Object.freeze(['verified', 'derived', 'estimated']);

// Runtime documentation for the API contract until the project adopts TypeScript.
export const dashboardResponseShape = Object.freeze({
  period: ['days', 'startDate', 'endDate'],
  metrics: ['id', 'labelKey', 'value', 'format', 'icon', 'dataStatus'],
  salesOverview: ['points', 'currency', 'dataStatus', 'source', 'updatedAt'],
  inventoryStatus: ['totals', 'items', 'dataStatus'],
  demandForecast: ['rows', 'dataStatus', 'source', 'updatedAt'],
  competitorComparison: ['rows', 'currency', 'dataStatus', 'source', 'updatedAt'],
  recentActivity: ['rows'],
});

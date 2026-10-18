const localized = (en, ar) => ({ en, ar });
const day = (offset) => {
  const value = new Date(Date.UTC(2026, 8, 15));
  value.setUTCDate(value.getUTCDate() + offset);
  return value.toISOString().slice(0, 10);
};

const series = (base, slope, lowerGap, upperGap) => Array.from({ length: 30 }, (_, index) => {
  const forecast = Math.max(0, Math.round(base + slope * index + Math.sin(index / 3) * 5));
  return { date: day(index + 1), forecast, lower: Math.max(0, forecast - lowerGap), upper: forecast + upperGap };
});

const products = [
  {
    id: 'product-workspace', name: localized('Team Workspace', 'مساحة عمل الفريق'), category: localized('Business Software', 'برمجيات الأعمال'),
    currentStock: 420, expectedDemand: 690, targetDate: day(30), confidenceRange: { lower: 610, upper: 770 }, trend: 'increasing', recommendedAction: 'restock',
    modelAccuracy: 91, suggestedQuantity: 270, priority: 'high', dataStatus: 'estimated', stockDataStatus: 'verified', forecast: series(17, .42, 4, 5),
    history: Array.from({ length: 14 }, (_, index) => ({ date: day(index - 13), actual: 14 + ((index * 3) % 9) })),
    aiInsight: { text: localized('Demand is expected to rise gradually within the current forecast horizon.', 'من المتوقع أن يرتفع الطلب تدريجياً ضمن أفق التوقع الحالي.'), generatedAt: '2026-09-15T08:00:00Z', confidence: .86, dataStatus: 'estimated' },
  },
  {
    id: 'product-insights', name: localized('Insights Package', 'حزمة الرؤى'), category: localized('Analytics', 'التحليلات'),
    currentStock: 305, expectedDemand: 248, targetDate: day(30), confidenceRange: { lower: 220, upper: 282 }, trend: 'decreasing', recommendedAction: 'reduce',
    modelAccuracy: 87, suggestedQuantity: 0, priority: 'medium', dataStatus: 'estimated', stockDataStatus: 'verified', forecast: series(11, -.16, 3, 4),
    history: Array.from({ length: 14 }, (_, index) => ({ date: day(index - 13), actual: 16 - Math.floor(index / 4) + (index % 3) })),
    aiInsight: null,
  },
  {
    id: 'product-support', name: localized('Support Add-on', 'إضافة الدعم'), category: localized('Customer Service', 'خدمة العملاء'),
    currentStock: 188, expectedDemand: 194, targetDate: day(30), confidenceRange: { lower: 175, upper: 216 }, trend: 'stable', recommendedAction: 'monitor',
    modelAccuracy: 89, suggestedQuantity: 0, priority: 'low', dataStatus: 'estimated', stockDataStatus: 'verified', forecast: series(6, .03, 2, 3),
    history: Array.from({ length: 14 }, (_, index) => ({ date: day(index - 13), actual: 6 + (index % 3) })),
    aiInsight: { text: localized('Expected demand remains within the recent operating range.', 'يبقى الطلب المتوقع ضمن نطاق التشغيل الأخير.'), generatedAt: '2026-09-15T08:00:00Z', confidence: .79, dataStatus: 'estimated' },
  },
];

function selectedProducts(productId) {
  return productId && productId !== 'all' ? products.filter((product) => product.id === productId) : products;
}

function aggregateForecast(rows, periodDays) {
  return Array.from({ length: periodDays }, (_, index) => ({
    date: day(index + 1),
    value: rows.reduce((sum, product) => sum + (product.forecast[index]?.forecast || 0), 0),
  }));
}

export function getMockDemandOverview({ productId = 'all', periodDays = 30 } = {}) {
  const selected = selectedProducts(productId);
  const days = [7, 30].includes(periodDays) ? periodDays : 30;
  return {
    companyId: 'company-preview',
    filters: { productId, periodDays: days },
    availablePeriods: [7, 30],
    products: products.map(({ id, name, category }) => ({ id, name, category })),
    metrics: [
      { id: 'next30Forecast', value: selected.reduce((sum, product) => sum + product.expectedDemand, 0), dataStatus: 'estimated', icon: 'calendar' },
      { id: 'productsForecasted', value: selected.length, dataStatus: 'verified', icon: 'package' },
      { id: 'predictedIncrease', value: selected.filter((product) => product.trend === 'increasing').length, dataStatus: 'derived', icon: 'increase' },
      { id: 'predictedDecrease', value: selected.filter((product) => product.trend === 'decreasing').length, dataStatus: 'derived', icon: 'decrease' },
      { id: 'stableDemand', value: selected.filter((product) => product.trend === 'stable').length, dataStatus: 'derived', icon: 'stable' },
    ],
    totalForecast: { points: aggregateForecast(selected, days), dataStatus: 'estimated' },
    forecasts: selected.map(({ forecast, history, aiInsight, ...product }) => product),
  };
}

export function getMockDemandDetail(productId) {
  const product = products.find((item) => item.id === productId);
  if (!product) return null;
  const chart = [
    ...product.history.map((point) => ({ date: point.date, actual: point.actual, forecast: null, lower: null, upper: null })),
    ...product.forecast.map((point) => ({ ...point, actual: null })),
  ];
  return {
    companyId: 'company-preview',
    product: { id: product.id, name: product.name, category: product.category },
    metrics: [
      { id: 'currentStock', value: product.currentStock, dataStatus: product.stockDataStatus, format: 'units' },
      { id: 'expectedDemand', value: product.expectedDemand, dataStatus: product.dataStatus, format: 'units' },
      { id: 'targetDate', value: product.targetDate, dataStatus: product.dataStatus, format: 'date' },
      { id: 'confidenceRange', value: product.confidenceRange, dataStatus: product.dataStatus, format: 'range' },
      { id: 'modelAccuracy', value: product.modelAccuracy, dataStatus: 'derived', format: 'percent' },
    ],
    chart: { points: chart, dataStatus: product.dataStatus },
    forecastHistory: product.forecast.map((point) => ({ id: `${product.id}-${point.date}`, date: point.date, forecastedDemand: point.forecast, lowerBound: point.lower, upperBound: point.upper, actualDemand: null, dataStatus: product.dataStatus })),
    recommendation: { action: product.recommendedAction, suggestedQuantity: product.suggestedQuantity, priority: product.priority, targetDate: product.targetDate, modelAccuracy: product.modelAccuracy, dataStatus: product.dataStatus },
    aiInsight: product.aiInsight,
  };
}

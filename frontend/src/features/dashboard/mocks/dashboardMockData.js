// API-shaped development data. Keep company-specific examples out of presentation components.
const localized = (en, ar) => ({ en, ar });
const isoDay = (daysAgo) => {
  const date = new Date(Date.UTC(2026, 8, 15));
  date.setUTCDate(date.getUTCDate() - daysAgo);
  return date.toISOString().slice(0, 10);
};

const salesHistory = Array.from({ length: 90 }, (_, index) => ({
  date: isoDay(89 - index),
  value: 330 + ((index * 47) % 260) + Math.round(Math.sin(index / 4) * 70),
}));

const baseDashboard = {
  company: { id: 'company-preview', currency: 'JOD', locale: 'en' },
  availablePeriods: [7, 30, 90],
  metrics: [
    { id: 'totalSales', labelKey: 'dashboard.kpis.totalSales', value: 12420, format: 'currency', icon: 'sales', tone: 'blue', dataStatus: 'verified' },
    { id: 'totalProducts', labelKey: 'dashboard.kpis.totalProducts', value: 248, format: 'number', icon: 'products', tone: 'purple', dataStatus: 'verified' },
    { id: 'trackedCompetitors', labelKey: 'dashboard.kpis.trackedCompetitors', value: 18, format: 'number', icon: 'competitors', tone: 'teal', dataStatus: 'verified' },
    { id: 'revenues', labelKey: 'dashboard.kpis.revenues', value: 38750, format: 'currency', icon: 'revenue', tone: 'purple', dataStatus: 'derived' },
    { id: 'inventoryStatus', labelKey: 'dashboard.kpis.inventoryStatus', value: 84, format: 'percent', icon: 'inventory', tone: 'orange', dataStatus: 'derived' },
    { id: 'marketSentiment', labelKey: 'dashboard.kpis.marketSentiment', value: 'positive', format: 'sentiment', icon: 'sentiment', tone: 'green', dataStatus: 'estimated' },
    { id: 'growth', labelKey: 'dashboard.kpis.growth', value: 12.8, format: 'signedPercent', icon: 'growth', tone: 'green', dataStatus: 'derived' },
  ],
  salesOverview: {
    dataStatus: 'verified',
    currency: 'JOD',
    updatedAt: '2026-09-15T07:30:00Z',
    points: salesHistory,
  },
  inventoryStatus: {
    dataStatus: 'verified',
    totals: { inStock: 203, lowStock: 31, outOfStock: 14, totalItems: 248 },
    items: [
      { id: 'inventory-1', product: localized('Essential Office Bundle', 'حزمة المكتب الأساسية'), quantity: 68 },
      { id: 'inventory-2', product: localized('Professional Analytics Plan', 'خطة التحليلات الاحترافية'), quantity: 31 },
      { id: 'inventory-3', product: localized('Executive Insights Pack', 'حزمة الرؤى التنفيذية'), quantity: 14 },
      { id: 'inventory-4', product: localized('Team Collaboration Suite', 'حزمة تعاون الفريق'), quantity: 9 },
    ],
  },
  demandForecast: {
    dataStatus: 'estimated',
    source: 'forecast-model',
    rows: [
      { id: 'forecast-1', product: localized('Essential Office Bundle', 'حزمة المكتب الأساسية'), forecastedDemand: 184 },
      { id: 'forecast-2', product: localized('Professional Analytics Plan', 'خطة التحليلات الاحترافية'), forecastedDemand: 126 },
      { id: 'forecast-3', product: localized('Executive Insights Pack', 'حزمة الرؤى التنفيذية'), forecastedDemand: 92 },
      { id: 'forecast-4', product: localized('Team Collaboration Suite', 'حزمة تعاون الفريق'), forecastedDemand: 76 },
    ],
  },
  competitorComparison: {
    dataStatus: 'derived',
    currency: 'JOD',
    rows: [
      { id: 'comparison-1', product: localized('Essential Office Bundle', 'حزمة المكتب الأساسية'), ourPrice: 49, lowestCompetitorPrice: 45 },
      { id: 'comparison-2', product: localized('Professional Analytics Plan', 'خطة التحليلات الاحترافية'), ourPrice: 89, lowestCompetitorPrice: 92 },
      { id: 'comparison-3', product: localized('Executive Insights Pack', 'حزمة الرؤى التنفيذية'), ourPrice: 129, lowestCompetitorPrice: 121 },
      { id: 'comparison-4', product: localized('Team Collaboration Suite', 'حزمة تعاون الفريق'), ourPrice: 69, lowestCompetitorPrice: 67 },
    ],
  },
  recentActivity: {
    rows: [
      { id: 'activity-1', date: '2026-09-15', activity: localized('File uploaded', 'تم رفع ملف'), details: localized('Quarterly sales data was imported.', 'تم استيراد بيانات المبيعات الفصلية.'), status: 'completed' },
      { id: 'activity-2', date: '2026-09-14', activity: localized('New competitor tracked', 'تمت متابعة منافس جديد'), details: localized('Market monitoring was enabled.', 'تم تفعيل مراقبة السوق.'), status: 'completed' },
      { id: 'activity-3', date: '2026-09-13', activity: localized('Forecast generated', 'تم إنشاء توقع'), details: localized('Next-week demand forecast is processing.', 'توقع الطلب للأسبوع المقبل قيد المعالجة.'), status: 'processing' },
      { id: 'activity-4', date: '2026-09-12', activity: localized('Product added', 'تمت إضافة منتج'), details: localized('A catalog item was added successfully.', 'تمت إضافة عنصر إلى الكتالوج بنجاح.'), status: 'completed' },
    ],
  },
};

export function getMockDashboard(periodDays = 30) {
  const days = baseDashboard.availablePeriods.includes(periodDays) ? periodDays : 30;
  return {
    ...baseDashboard,
    period: { days, startDate: isoDay(days - 1), endDate: isoDay(0) },
    salesOverview: { ...baseDashboard.salesOverview, points: baseDashboard.salesOverview.points.slice(-days) },
  };
}

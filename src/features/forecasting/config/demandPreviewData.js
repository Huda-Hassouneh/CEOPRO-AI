export const demandRoutePaths = Object.freeze({
  overview: '/demand',
  products: '/demand/products',
  productDetail: '/demand/products/:productId',
  inventory: '/demand/inventory',
});

const product = (id, name, sku, categoryKey, stock, forecast, change, accuracy, tone, trend) => ({
  id, name, sku, categoryKey, stock, forecast, change, accuracy, tone, trend,
});

export const demandProducts = [
  product('acoustic-pro-speaker', 'Acoustic Pro Speaker', 'AP-2049', 'demand.categories.electronics', 620, 1240, 100, 92, 'increasing', [28, 35, 42, 48, 61, 70, 84]),
  product('glow-face-serum', 'Glow Face Serum', 'FS-7781', 'demand.categories.beauty', 320, 720, 80, 88, 'increasing', [24, 30, 42, 49, 57, 72, 78]),
  product('ergonomic-chair', 'Ergonomic Chair', 'CH-3102', 'demand.categories.office', 150, 315, 110, 90, 'increasing', [23, 29, 36, 48, 55, 67, 79]),
  product('smart-watch-x', 'Smart Watch X', 'WT-9920', 'demand.categories.electronics', 410, 820, 100, 87, 'increasing', [31, 38, 44, 53, 60, 75, 83]),
  product('organic-green-tea', 'Organic Green Tea', 'GT-5021', 'demand.categories.food', 200, 380, 90, 88, 'increasing', [22, 28, 34, 46, 59, 68, 76]),
  product('winter-jacket', 'Winter Jacket', 'JK-1108', 'demand.categories.apparel', 890, 450, -49, 86, 'decreasing', [82, 75, 68, 60, 51, 43, 34]),
  product('beach-umbrella', 'Beach Umbrella', 'BU-2711', 'demand.categories.outdoor', 620, 320, -48, 82, 'decreasing', [78, 71, 65, 56, 49, 41, 33]),
  product('board-game-set', 'Board Game Set', 'BG-7708', 'demand.categories.toys', 530, 290, -45, 80, 'decreasing', [76, 70, 61, 55, 47, 39, 31]),
  product('desk-lamp', 'Desk Lamp', 'DL-7706', 'demand.categories.office', 310, 180, -42, 84, 'decreasing', [72, 66, 59, 51, 44, 37, 29]),
];

export const demandOverview = {
  snapshot: [
    { id: 'week', labelKey: 'demand.overview.nextWeek', value: '12,400', suffixKey: 'demand.common.units', trend: '+4.2%', icon: 'calendar', series: [22, 30, 27, 40, 38, 51] },
    { id: 'month', labelKey: 'demand.overview.next30Days', value: '58,100', suffixKey: 'demand.common.units', trend: '+8.7%', icon: 'calendar', series: [20, 25, 32, 29, 44, 53] },
    { id: 'products', labelKey: 'demand.overview.productsForecasted', value: '245', detail: '/ 500', progress: 49, icon: 'package' },
    { id: 'spikes', labelKey: 'demand.overview.spikesDetected', value: '6', detailKey: 'demand.overview.spikesDetail', icon: 'activity', tone: 'negative' },
  ],
  trend: {
    labels: ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'].map((month) => `demand.months.${month}`),
    current: [6200, 7100, 8600, 8200, 9100, 9800, 10400, 11200, 10800, 12100, 13900, 16100],
    previous: [5700, 6500, 7200, 7500, 7900, 8500, 9100, 9500, 9900, 10700, 11900, 13200],
  },
  inventoryActions: [
    { productId: 'acoustic-pro-speaker', action: 'restock', quantity: '+620', reasonKey: 'demand.reasons.highIncrease' },
    { productId: 'glow-face-serum', action: 'restock', quantity: '+400', reasonKey: 'demand.reasons.trending' },
    { productId: 'winter-jacket', action: 'reduce', quantity: '-440', reasonKey: 'demand.reasons.lowerDemand' },
    { productId: 'beach-umbrella', action: 'reduce', quantity: '-300', reasonKey: 'demand.reasons.seasonalDecline' },
    { productId: 'desk-lamp', action: 'monitor', quantity: '—', reasonKey: 'demand.reasons.review' },
  ],
  opportunities: [
    { id: 'bundle', titleKey: 'demand.opportunities.bundle', descriptionKey: 'demand.opportunities.bundleText', potential: 'high', icon: 'wifi' },
    { id: 'seasonal', titleKey: 'demand.opportunities.seasonal', descriptionKey: 'demand.opportunities.seasonalText', potential: 'medium', icon: 'gift' },
    { id: 'mobile', titleKey: 'demand.opportunities.mobile', descriptionKey: 'demand.opportunities.mobileText', potential: 'medium', icon: 'mobile' },
  ],
};

export const productForecastSummary = [
  { labelKey: 'demand.products.totalProducts', value: '245', detailKey: 'demand.products.totalProductsDetail', icon: 'package' },
  { labelKey: 'demand.products.expectedIncrease', value: '142', detailKey: 'demand.products.expectedIncreaseDetail', icon: 'trendUp', tone: 'positive' },
  { labelKey: 'demand.products.expectedDecrease', value: '63', detailKey: 'demand.products.expectedDecreaseDetail', icon: 'trendDown', tone: 'negative' },
  { labelKey: 'demand.products.stableDemand', value: '40', detailKey: 'demand.products.stableDemandDetail', icon: 'stable' },
];

export const demandProductDetails = {
  'acoustic-pro-speaker': {
    productId: 'acoustic-pro-speaker',
    kpis: [
      { labelKey: 'demand.detail.currentStock', value: '620', suffixKey: 'demand.common.units', icon: 'package' },
      { labelKey: 'demand.detail.forecast30', value: '1,240', suffixKey: 'demand.common.units', trend: '+42%', icon: 'trendUp' },
      { labelKey: 'demand.detail.modelAccuracy', value: '92%', detailKey: 'demand.detail.highReliability', icon: 'target' },
      { labelKey: 'demand.detail.dailyDemand', value: '41', suffixKey: 'demand.common.units', trend: '+35%', icon: 'bars' },
      { labelKey: 'demand.detail.revenueOpportunity', value: '+12%', detail: '(1,200 JOD)', icon: 'money' },
    ],
    chart: {
      labels: ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'].map((month) => `demand.months.${month}`),
      historical: [620, 700, 670, 760, 820, 860],
      predicted: [860, 980, 1050, 1110, 1180, 1240],
      lower: [860, 900, 960, 1010, 1060, 1100],
      upper: [860, 1060, 1160, 1240, 1340, 1420],
    },
    forecastRows: [
      ['demand.periods.jul2026', '860', '860', '820', '900'],
      ['demand.periods.aug2026', '—', '980', '900', '1,060'],
      ['demand.periods.sep2026', '—', '1,050', '960', '1,160'],
      ['demand.periods.oct2026', '—', '1,110', '1,010', '1,240'],
      ['demand.periods.nov2026', '—', '1,180', '1,060', '1,340'],
      ['demand.periods.dec2026', '—', '1,240', '1,100', '1,420'],
    ],
    heatmap: [
      [1,1,2,2,2,3,3,3,4,4,3,2], [1,2,2,3,3,4,4,5,5,4,3,2],
      [1,1,2,2,3,3,4,5,5,5,4,3], [1,2,2,3,4,4,5,5,4,4,3,2],
    ],
  },
};

export const getDemandProduct = (id) => demandProducts.find((item) => item.id === id);

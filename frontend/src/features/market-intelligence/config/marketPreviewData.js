export const marketOverviewMetrics = [
  { id: 'competitors', labelKey: 'market.metrics.competitors', value: '12', trend: '↑ 2', trendKey: 'market.common.thisMonth', tone: 'purple', icon: 'competitors' },
  { id: 'sentiment', labelKey: 'market.metrics.sentiment', value: '72', trend: '↑ 4 pts', trendKey: 'market.common.thisMonth', tone: 'green', icon: 'sentiment', progress: 72 },
  { id: 'price', labelKey: 'market.metrics.price', value: '7.8 / 10', trend: '↓ 0.4', trendKey: 'market.common.vsLastMonth', tone: 'purple', icon: 'price' },
  { id: 'growth', labelKey: 'market.metrics.growth', value: '+8%', trend: '↑ 2%', trendKey: 'market.common.vsLastYear', tone: 'green', icon: 'growth' },
];

export const industryMetrics = [
  { id: 'providers', labelKey: 'market.industry.metrics.providers', value: '18', trend: '↑ 2 new', trendKey: 'market.common.vsLastQuarter', tone: 'purple', icon: 'competitors' },
  { id: 'monthlyPrice', labelKey: 'market.industry.metrics.monthlyPrice', value: '32 JOD', trend: '↓ 5%', trendKey: 'market.common.vsPreviousPeriod', tone: 'red', icon: 'price' },
  { id: 'activity', labelKey: 'market.industry.metrics.activity', valueKey: 'market.industry.high', trend: '↑ 12%', trendKey: 'market.common.vsLastQuarter', tone: 'green', icon: 'growth' },
  { id: 'growth', labelKey: 'market.metrics.growth', value: '+8%', trend: '↑ 2%', trendKey: 'market.common.vsLastYear', tone: 'green', icon: 'growth' },
];

export const marketTrendSeries = { current: [72, 86, 98, 96, 106, 112, 110, 124, 127, 126, 141, 150], previous: [62, 72, 78, 77, 87, 89, 90, 94, 96, 104, 115, 126] };
export const priceTrendSeries = { current: [72, 84, 92, 92, 101, 106, 106, 112, 120, 120, 128, 135], previous: [66, 75, 77, 77, 86, 88, 91, 92, 94, 101, 105, 114] };
export const seasonalSeries = { historical: [28, 24, 20, 35], current: [32, 27, 26, 42] };

export const positiveDrivers = ['market.drivers.remoteWork', 'market.drivers.fiberInfrastructure', 'market.drivers.highSpeeds', 'market.drivers.digitalServices'];
export const negativeDrivers = ['market.drivers.priceSensitivity', 'market.drivers.competition', 'market.drivers.economicUncertainty', 'market.drivers.regulatoryPressure'];

export const competitorPreview = [
  { name: 'Orange', domain: 'orange.jo', sentimentKey: 'market.status.positive', price: '7.5/10', activityKey: 'market.status.high', activityKey2: 'market.competitors.newPackage', updatedKey: 'market.common.twoHours', tone: 'positive', color: '#f97316' },
  { name: 'Zain', domain: 'zain.com', sentimentKey: 'market.status.neutral', price: '6.8/10', activityKey: 'market.status.high', activityKey2: 'market.competitors.priceDrop', updatedKey: 'market.common.oneDay', tone: 'neutral', color: '#111827' },
  { name: 'Umniah', domain: 'umniah.com', sentimentKey: 'market.status.positive', price: '7.2/10', activityKey: 'market.status.high', activityKey2: 'market.competitors.newCampaign', updatedKey: 'market.common.twoDays', tone: 'positive', color: '#84cc16' },
  { name: 'Vortex Data', domain: 'vortexdata.co', sentimentKey: 'market.status.negative', price: '8.1/10', activityKey: 'market.status.high', activityKey2: 'market.competitors.bundlePricing', updatedKey: 'market.common.threeDays', tone: 'negative', color: '#dc2626' },
  { name: 'Nova Insights', domain: 'novainsights.io', sentimentKey: 'market.status.neutral', price: '5.9/10', activityKey: 'market.status.medium', activityKey2: 'market.competitors.newProduct', updatedKey: 'market.common.fourDays', tone: 'neutral', color: '#0ea5a8' },
];

export const competitorActivity = [
  { name: 'Orange', activityKey: 'market.competitors.launchedFiber', timeKey: 'market.common.twoHours', color: '#f97316', badgeKey: 'market.badges.newProduct' },
  { name: 'Zain', activityKey: 'market.competitors.priceDrop', timeKey: 'market.common.fiveHours', color: '#111827', badgeKey: 'market.badges.priceChange' },
  { name: 'Umniah', activityKey: 'market.competitors.newCampaign', timeKey: 'market.common.oneDay', color: '#84cc16', badgeKey: 'market.badges.marketing' },
  { name: 'Vortex Data', activityKey: 'market.competitors.bundlePricing', timeKey: 'market.common.twoDays', color: '#dc2626', badgeKey: 'market.badges.pricing' },
  { name: 'Vortex Data', activityKey: 'market.competitors.newProduct', timeKey: 'market.common.threeDays', color: '#dc2626', badgeKey: 'market.badges.newProduct' },
];

export const opportunitiesPreview = [
  { id: 'speed', titleKey: 'market.opportunities.highSpeed', potentialKey: 'market.status.highPotential', descriptionKey: 'market.opportunities.highSpeedDescription', tone: 'green' },
  { id: 'smart-home', titleKey: 'market.opportunities.smartHome', potentialKey: 'market.status.mediumPotential', descriptionKey: 'market.opportunities.smartHomeDescription', tone: 'green' },
  { id: 'mobile-internet', titleKey: 'market.opportunities.mobileInternet', potentialKey: 'market.status.mediumPotential', descriptionKey: 'market.opportunities.mobileInternetDescription', tone: 'yellow' },
];

export const categoryActivity = [
  { labelKey: 'market.categories.homeInternet', value: 42 }, { labelKey: 'market.categories.mobileBundles', value: 28 }, { labelKey: 'market.categories.fixedWireless', value: 16 }, { labelKey: 'market.categories.tv', value: 8 }, { labelKey: 'market.categories.smartHome', value: 4 }, { labelKey: 'market.categories.other', value: 2 },
];
export const emergingTrends = [
  { rank: 1, titleKey: 'market.emerging.bundled', descriptionKey: 'market.emerging.bundledDescription', impactKey: 'market.status.highImpact' }, { rank: 2, titleKey: 'market.emerging.fiveG', descriptionKey: 'market.emerging.fiveGDescription', impactKey: 'market.status.highImpact' }, { rank: 3, titleKey: 'market.emerging.smartHome', descriptionKey: 'market.emerging.smartHomeDescription', impactKey: 'market.status.mediumImpact' }, { rank: 4, titleKey: 'market.emerging.sustainability', descriptionKey: 'market.emerging.sustainabilityDescription', impactKey: 'market.status.mediumImpact' },
];
export const marketSignals = [
  { indicatorKey: 'market.signals.priceTrend', currentKey: 'market.signals.increasing', change: '↑ 6%', insightKey: 'market.signals.priceInsight' }, { indicatorKey: 'market.signals.activity', currentKey: 'market.signals.high', change: '↑ 12%', insightKey: 'market.signals.activityInsight' }, { indicatorKey: 'market.signals.sentiment', currentKey: 'market.signals.positive', change: '↑ 4%', insightKey: 'market.signals.sentimentInsight' }, { indicatorKey: 'market.signals.product', currentKey: 'market.signals.increasing', change: '↑ 18%', insightKey: 'market.signals.productInsight' }, { indicatorKey: 'market.signals.competitor', currentKey: 'market.signals.high', change: '↑ 15%', insightKey: 'market.signals.competitorInsight' },
];

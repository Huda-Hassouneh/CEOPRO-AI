export const competitorRows = [
  ['Orange', 'orange.jo', 'Telecom', 'market.status.positive', '7.5/10', 'market.status.high', 'market.competitors.newPackage', 'market.common.twoHours', 'positive', '#f97316'],
  ['Zain', 'zain.com', 'Telecom', 'market.status.neutral', '6.8/10', 'market.status.medium', 'market.competitors.priceDrop', 'market.common.oneDay', 'neutral', '#111827'],
  ['Umniah', 'umniah.com', 'Telecom', 'market.status.positive', '7.2/10', 'market.status.high', 'market.competitors.newCampaign', 'market.common.twoDays', 'positive', '#84cc16'],
  ['Vortex Data', 'vortexdata.co', 'Internet', 'market.status.negative', '8.1/10', 'market.status.high', 'market.competitors.bundlePricing', 'market.common.threeDays', 'negative', '#dc2626'],
  ['Nova Insights', 'novainsights.io', 'Analytics', 'market.status.neutral', '5.9/10', 'market.status.medium', 'market.competitors.newProduct', 'market.common.fourDays', 'neutral', '#0ea5a8'],
  ['FiberNet', 'fibernet.jo', 'Internet', 'market.status.positive', '6.4/10', 'market.status.low', 'market.competitors.coverage', 'market.common.oneWeek', 'positive', '#1d4ed8'],
  ['Speed Connect', 'speedconnect.jo', 'Internet', 'market.status.neutral', '6.9/10', 'market.status.medium', 'market.competitors.mobilePlan', 'market.common.oneWeek', 'neutral', '#dc2626'],
  ['NetStream', 'netstream.com', 'Digital Services', 'market.status.positive', '7.0/10', 'market.status.medium', 'market.competitors.partnership', 'market.common.oneWeek', 'positive', '#06b6d4'],
  ['LinkPlus', 'linkplus.jo', 'Telecom', 'market.status.negative', '5.6/10', 'market.status.low', 'market.competitors.newCampaign', 'market.common.oneWeek', 'negative', '#4f46e5'],
  ['Jordan Telecom', 'jordantelecom.jo', 'Telecom', 'market.status.neutral', '6.3/10', 'market.status.medium', 'market.competitors.bundlePricing', 'market.common.oneWeek', 'neutral', '#0f766e'],
];

export const previewCompetitors = [];
export function addPreviewCompetitor(values) {
  previewCompetitors.unshift([values.name, values.website.replace(/^https?:\/\//, ''), 'Telecom', 'market.status.neutral', '6.0/10', 'market.status.medium', 'market.competitors.newProduct', 'market.common.twoHours', 'neutral', '#6366f1']);
}

export const orangeDetail = {
  name: 'Orange', domain: 'orange.jo', updatedKey: 'market.common.twoHours', descriptionKey: 'market.detail.orangeDescription', color: '#f97316', tracked: true,
  metrics: [{ labelKey: 'market.detail.sentiment', valueKey: 'market.status.positive', sub: '72/100', trend: '↑ 6%', icon: 'sentiment', tone: 'green' }, { labelKey: 'market.metrics.price', value: '7.5 / 10', sub: '', trend: '↓ 0.4', icon: 'price', tone: 'purple' }, { labelKey: 'market.detail.activity', valueKey: 'market.status.high', sub: '95/100', trend: '↑ 12%', icon: 'growth', tone: 'blue' }, { labelKey: 'market.detail.relevance', value: '94.5 / 100', sub: '#1', trend: '', icon: 'relevance', tone: 'purple' }],
  presence: { current: [8, 15, 20, 20, 24, 27, 28, 30, 33, 33, 38, 42], previous: [6, 10, 12, 13, 18, 19, 19, 20, 21, 22, 24, 29] },
  summary: [{ labelKey: 'market.detail.headquarters', value: 'Amman, Jordan' }, { labelKey: 'market.detail.marketPosition', value: '#1' }, { labelKey: 'market.detail.primaryFocus', value: 'Mobile, Home Internet' }, { labelKey: 'market.detail.website', value: 'https://www.orange.jo' }],
  strengths: ['market.detail.strongRecognition', 'market.detail.wideCoverage', 'market.detail.bundledPackages', 'market.detail.activePresence'], weaknesses: ['market.detail.higherPrices', 'market.detail.customerComplaints', 'market.detail.limitedFlexibility', 'market.detail.slowerNicheResponse'],
  moves: [{ titleKey: 'market.competitors.launchedFiber', timeKey: 'market.common.twoDays' }, { titleKey: 'market.detail.startedFiveG', timeKey: 'market.common.oneDay' }, { titleKey: 'market.detail.selfServiceApp', timeKey: 'market.common.oneDay' }, { titleKey: 'market.detail.providerPartnership', timeKey: 'market.common.twoDays' }],
  products: [{ id: 'product-1', name: 'Ultra Speed 500', categoryKey: 'marketScoped.category.homeInternet', typeKey: 'marketScoped.type.fiber', price: '22.00', updatedKey: 'market.common.twoDays' }, { id: 'product-2', name: 'Ultra Speed 250', categoryKey: 'marketScoped.category.homeInternet', typeKey: 'marketScoped.type.fiber', price: '16.00', updatedKey: 'market.common.twoDays' }, { id: 'product-3', name: '5G Postpaid 50', categoryKey: 'marketScoped.category.mobile', typeKey: 'marketScoped.type.postpaid', price: '18.00', updatedKey: 'market.common.oneDay' }, { id: 'product-4', name: '5G Postpaid 30', categoryKey: 'marketScoped.category.mobile', typeKey: 'marketScoped.type.postpaid', price: '12.00', updatedKey: 'market.common.oneDay' }, { id: 'product-5', name: 'Orange TV', categoryKey: 'marketScoped.category.digitalServices', typeKey: 'marketScoped.type.tv', price: '7.00', updatedKey: 'market.common.threeDays' }],
  priceComparison: [{ name: 'Orange', value: 22 }, { name: 'Zain', value: 24 }, { name: 'Umniah', value: 26 }],
  activity: [{ titleKey: 'market.detail.newProductLaunched', description: 'Ultra Speed 500 package', timeKey: 'market.common.twoDays' }, { titleKey: 'market.detail.priceChanged', description: 'Price changed from 24.00 to 22.00 JOD', timeKey: 'market.common.oneDay' }, { titleKey: 'market.detail.campaignDetected', description: 'More for You digital campaign', timeKey: 'market.common.oneDay' }, { titleKey: 'market.detail.bundleUpdated', description: 'Home internet + TV bundle', timeKey: 'market.common.twoDays' }, { titleKey: 'market.detail.serviceDetected', description: 'Smart home solutions', timeKey: 'market.common.twoDays' }],
};

export const competitorDetailsById = { orange: orangeDetail, zain: orangeDetail, umniah: orangeDetail };

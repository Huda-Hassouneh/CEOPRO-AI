const localized = (en, ar) => ({ en, ar });

const productAnalyses = {
  'product-operations': {
    metrics: [
      { id: 'totalCompetitors', value: 8, format: 'number', icon: 'users', dataStatus: 'verified' },
      { id: 'averageCompositeScore', value: 74, format: 'score100', icon: 'composite', dataStatus: 'derived' },
      { id: 'topSegmentScore', value: 8.6, format: 'score10', icon: 'segment', dataStatus: 'estimated' },
      { id: 'averagePriceScore', value: 7.8, format: 'score10', icon: 'price', dataStatus: 'derived' },
    ],
    aiMarketIntelligence: {
      insight: localized('Competition is intensifying in workflow products while demand remains resilient among growing teams.', 'تشتد المنافسة في منتجات سير العمل بينما يظل الطلب قوياً لدى الفرق النامية.'),
      drivers: [
        { id: 'driver-1', direction: 'positive', type: 'demand', text: localized('Search interest from mid-sized teams is rising.', 'يتزايد اهتمام الفرق متوسطة الحجم بالبحث.') },
        { id: 'driver-2', direction: 'positive', type: 'sentiment', text: localized('Customer feedback favors simple onboarding.', 'تفضل آراء العملاء سهولة الإعداد.') },
        { id: 'driver-3', direction: 'negative', type: 'pricing', text: localized('Two competitors reduced entry-level pricing.', 'خفض منافسان أسعار الباقات الأساسية.') },
        { id: 'driver-4', direction: 'negative', type: 'activity', text: localized('Promotional activity increased this period.', 'ازداد النشاط الترويجي خلال هذه الفترة.') },
      ],
      sentiment: 'positive',
      sentimentSummary: localized('Market perception is positive, led by usability and support quality.', 'نظرة السوق إيجابية مدفوعة بسهولة الاستخدام وجودة الدعم.'),
      generatedAt: '2026-09-15T08:30:00Z',
      confidence: 0.82,
      dataStatus: 'estimated',
    },
    competitors: [
      ['competitor-1', 'Northstar Commerce', 8.1, 82, 91, 88, 'positive'],
      ['competitor-2', 'Meridian Systems', 7.4, 76, 84, 80, 'neutral'],
      ['competitor-3', 'Summit Works', 8.5, 79, 78, 74, 'positive'],
      ['competitor-4', 'Harbor Digital', 6.8, 68, 72, 70, 'negative'],
    ],
    pricingRecommendations: [
      { id: 'price-1', currentPrice: 64, action: 'hold', suggestedPrice: 64, marketMin: 52, marketMax: 79, marketAverage: 65, marketMedian: 63, matchedCompetitors: 8, explanation: localized('Current price is aligned with the market.', 'السعر الحالي متوافق مع السوق.'), dataStatus: 'derived' },
    ],
    recentPriceChanges: [
      { id: 'change-1', date: '2026-09-14', competitor: 'Meridian Systems', previousPrice: 69, newPrice: 62, direction: 'decreased', detectedAt: '2026-09-14T10:40:00Z', dataStatus: 'verified' },
      { id: 'change-2', date: '2026-09-12', competitor: 'Summit Works', previousPrice: 71, newPrice: 74, direction: 'increased', detectedAt: '2026-09-12T16:10:00Z', dataStatus: 'verified' },
    ],
  },
  'product-analytics': {
    metrics: [
      { id: 'totalCompetitors', value: 5, format: 'number', icon: 'users', dataStatus: 'verified' },
      { id: 'averageCompositeScore', value: 69, format: 'score100', icon: 'composite', dataStatus: 'derived' },
      { id: 'topSegmentScore', value: 7.9, format: 'score10', icon: 'segment', dataStatus: 'estimated' },
      { id: 'averagePriceScore', value: 8.2, format: 'score10', icon: 'price', dataStatus: 'derived' },
    ],
    aiMarketIntelligence: {
      insight: localized('Analytics buyers are prioritizing faster deployment and clearer reporting over feature breadth.', 'يعطي مشترو التحليلات الأولوية لسرعة النشر ووضوح التقارير على كثرة الميزات.'),
      drivers: [
        { id: 'driver-5', direction: 'positive', type: 'demand', text: localized('Reporting automation demand is increasing.', 'يتزايد الطلب على أتمتة التقارير.') },
        { id: 'driver-6', direction: 'positive', type: 'pricing', text: localized('Premium tiers retain pricing power.', 'تحتفظ الباقات المتميزة بقوة تسعير جيدة.') },
        { id: 'driver-7', direction: 'negative', type: 'activity', text: localized('New entrants are shortening trial cycles.', 'يقلص المنافسون الجدد فترات التجربة.') },
      ],
      sentiment: 'neutral',
      sentimentSummary: localized('Perception is balanced as strong reporting is offset by implementation concerns.', 'النظرة متوازنة؛ إذ تقابل قوة التقارير مخاوف التنفيذ.'),
      generatedAt: '2026-09-15T08:30:00Z',
      confidence: 0.76,
      dataStatus: 'estimated',
    },
    competitors: [
      ['competitor-5', 'Bluepeak Analytics', 8.4, 77, 86, 81, 'positive'],
      ['competitor-6', 'Cedar Metrics', 7.9, 71, 79, 76, 'neutral'],
      ['competitor-7', 'Atlas Reporting', 8.3, 73, 75, 69, 'neutral'],
    ],
    pricingRecommendations: [
      { id: 'price-2', currentPrice: 118, action: 'raise', suggestedPrice: 124, marketMin: 96, marketMax: 139, marketAverage: 121, marketMedian: 119, matchedCompetitors: 5, explanation: localized('Strong demand supports a measured increase.', 'يدعم الطلب القوي زيادة مدروسة.'), dataStatus: 'estimated' },
    ],
    recentPriceChanges: [
      { id: 'change-3', date: '2026-09-13', competitor: 'Cedar Metrics', previousPrice: 125, newPrice: 119, direction: 'decreased', detectedAt: '2026-09-13T09:20:00Z', dataStatus: 'verified' },
    ],
  },
};

const products = [
  { id: 'product-operations', name: localized('Operations Suite', 'حزمة العمليات'), currency: 'JOD' },
  { id: 'product-analytics', name: localized('Analytics Workspace', 'مساحة عمل التحليلات'), currency: 'JOD' },
];

export const marketIntelligenceMockData = {
  companyId: 'company-preview',
  availablePeriods: [30, 90],
  products,
  productAnalyses,
  expansionOpportunities: [
    { id: 'opportunity-1', productName: localized('Customer Support Hub', 'مركز دعم العملاء'), opportunityScore: 88, competitorCount: 4, competitors: ['Northstar Commerce', 'Cedar Metrics', 'Harbor Digital', 'Summit Works'], explanation: localized('Adjacent demand and limited specialist coverage indicate room for expansion.', 'يشير الطلب المجاور ومحدودية التغطية المتخصصة إلى فرصة للتوسع.'), dataStatus: 'estimated' },
    { id: 'opportunity-2', productName: localized('Mobile Reporting Add-on', 'إضافة التقارير المتنقلة'), opportunityScore: 81, competitorCount: 3, competitors: ['Bluepeak Analytics', 'Atlas Reporting', 'Meridian Systems'], explanation: localized('Mobile usage signals are growing faster than current market supply.', 'تنمو مؤشرات الاستخدام المتنقل بوتيرة أسرع من العرض الحالي في السوق.'), dataStatus: 'estimated' },
    { id: 'opportunity-3', productName: localized('Compliance Toolkit', 'أدوات الامتثال'), opportunityScore: 76, competitorCount: 2, competitors: ['Cedar Metrics', 'Summit Works'], explanation: localized('A small competitive field and recurring customer needs support validation.', 'يدعم قلة المنافسين واحتياجات العملاء المتكررة اختبار هذه الفرصة.'), dataStatus: 'estimated' },
  ],
};

export function getMockMarketIntelligence({ productId = products[0].id, periodDays = 30 } = {}) {
  const selectedProduct = products.find((product) => product.id === productId) || products[0];
  const analysis = productAnalyses[selectedProduct.id];
  const withProduct = (row) => ({ ...row, productId: selectedProduct.id, productName: selectedProduct.name });
  return {
    companyId: marketIntelligenceMockData.companyId,
    period: { days: marketIntelligenceMockData.availablePeriods.includes(periodDays) ? periodDays : 30 },
    availablePeriods: marketIntelligenceMockData.availablePeriods,
    products,
    selectedProduct,
    metrics: analysis.metrics,
    aiMarketIntelligence: analysis.aiMarketIntelligence,
    competitors: analysis.competitors.map(([competitorId, competitorName, pricingScore, compositeScore, relevanceScore, marketPresenceScore, marketPerception]) => withProduct({ id: `${selectedProduct.id}-${competitorId}`, competitorId, competitorName, pricingScore, compositeScore, relevanceScore, marketPresenceScore, marketPerception, dataStatus: 'derived' })),
    pricingRecommendations: analysis.pricingRecommendations.map(withProduct),
    expansionOpportunities: marketIntelligenceMockData.expansionOpportunities,
    recentPriceChanges: analysis.recentPriceChanges.map(withProduct),
  };
}

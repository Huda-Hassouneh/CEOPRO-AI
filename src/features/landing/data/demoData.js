// Fictional, presentation-only examples. Never used by business pages or APIs.
export const LANDING_DEMO = Object.freeze({
  revenue: 48250, sales: 1248, growth: 12.8, inventory: 86,
  demand: { expected: 620, low: 580, high: 665, stock: 410, reorder: 480, safety: 80 },
  pricing: { current: 24, suggested: 22.5, min: 20, average: 22.5, max: 25, matched: 3, confidence: 87, score: 8.4 },
  competitors: [
    { key: 'businessA', price: 20, availability: 'inStock', sentiment: 'positive' },
    { key: 'businessB', price: 22.5, availability: 'inStock', sentiment: 'positive' },
    { key: 'businessC', price: 25, availability: 'limited', sentiment: 'neutral' },
  ],
  sentiment: { positive: 72, neutral: 18, negative: 10, perception: 78, reviews: 240, confidence: 89 },
  scores: [{ key: 'price', value: 8.4, max: 10 }, { key: 'composite', value: 82, max: 100 }, { key: 'activity', value: 74, max: 100 }, { key: 'relevance', value: 91, max: 100 }],
  sources: [{ key: 'source1', relevance: 0.91 }, { key: 'source2', relevance: 0.86 }],
  extraction: { processed: 1240, partial: 12, failed: 3, headers: 96 },
});

import { Navigate } from 'react-router-dom';
import { routePaths } from '../../../app/router/routePaths.js';

// This route (/market/competitors/:competitorId/products/:productId) was
// 100% fabricated static content (hardcoded Orange logo, fake Zain/
// Umniah price bars, fake demand curves, fake sentiment donut) - there is
// no real backend concept of an individually-tracked "competitor
// product" with this depth. The real, honest equivalent - one
// competitor's real per-product your-price-vs-their-price comparison -
// already exists at features/market-intelligence/pages/
// CompetitorProfileDetailPage.jsx. Nothing else in the app links to this
// route, so it redirects to the real competitors list rather than
// showing fabricated data.
export function ProductDetailPage() {
  return <Navigate to={routePaths.marketCompetitors} replace />;
}

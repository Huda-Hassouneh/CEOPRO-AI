import { BarChart3, BrainCircuit, Boxes, ChartNoAxesCombined, CircleDollarSign, Lightbulb, MessageSquare, Package, ShoppingCart, Sparkles, TrendingUp, Users, Upload, WalletCards, AlertTriangle, Smile } from 'lucide-react';

const icons = { revenue: CircleDollarSign, sales: ShoppingCart, growth: TrendingUp, inventory: Boxes, competitors: Users, sentiment: Smile, products: Package, rag: MessageSquare, ai: BrainCircuit, upload: Upload, sale: WalletCards, forecast: ChartNoAxesCombined, alert: AlertTriangle, trend: TrendingUp, idea: Lightbulb, market: BarChart3, product: Package };
export function DashboardIcon({ name, size = 18 }) {
  const Icon = icons[name] || Sparkles;
  return <Icon size={size} aria-hidden="true" />;
}

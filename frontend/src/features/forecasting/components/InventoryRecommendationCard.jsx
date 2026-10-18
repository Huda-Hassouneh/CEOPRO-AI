import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function InventoryRecommendationCard() {
  const { t: copyT } = useI18n();
  return <div className="inventory-recommendation-card">{copyT("interfaceCopy.inventoryRecommendation")}</div>;
}

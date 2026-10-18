import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function StockLevelBadge() {
  const { t: copyT } = useI18n();
  return <span className="stock-level-badge">{copyT("interfaceCopy.stock")}</span>;
}

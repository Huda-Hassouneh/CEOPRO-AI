import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function QuickSaleModal() {
  const { t: copyT } = useI18n();
  return <div className="quick-sale-modal">{copyT("interfaceCopy.quickSale")}</div>;
}

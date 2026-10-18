import { useI18n } from '../../../app/providers/I18nProvider.jsx';
export function ProductTable() {
  const { t: copyT } = useI18n();
  return <div className="product-table">{copyT("interfaceCopy.productTable")}</div>;
}

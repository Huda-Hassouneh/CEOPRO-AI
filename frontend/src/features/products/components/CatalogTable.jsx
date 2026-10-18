import { Link } from 'react-router-dom';
import { Package } from 'lucide-react';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import { productText } from '../utils/productText.js';

export function CatalogTable({ products, t, locale, emptyAction, filtered }) {
  if (!products.length) return <EmptyState icon={<Package size={26} />} title={t(filtered ? 'catalog.ux.noMatches' : 'catalog.empty')} description={t(filtered ? 'catalog.ux.tryFilters' : 'catalog.ux.emptyHint')} action={emptyAction} />;
  return <div className="catalog-table-wrap" role="region" aria-label={t('catalog.title')} tabIndex={0}>
    <table><caption className="catalog-sr-only">{t('catalog.title')}</caption><thead><tr>
      {['name', 'sku', 'gtin', 'price', 'category'].map(field => <th scope="col" key={field}>{t(`catalog.fields.${field}`)}</th>)}
    </tr></thead><tbody>{products.map(product => <tr key={product.id}>
      <td><div className="catalog-product-cell"><span className="catalog-product-icon" aria-hidden="true"><Package size={19} /></span><div><Link to={`/products/${product.id}`}>{productText(product.name, locale)}</Link>{productText(product.brand, locale) !== '—' && <small>{productText(product.brand, locale)}</small>}</div></div></td>
      <td><bdi className="catalog-identifier">{product.sku || '—'}</bdi></td>
      <td><bdi className="catalog-identifier">{product.gtin || '—'}</bdi>{product.gtinDuplicate && <small className="catalog-note">{t('catalog.gtin.duplicate')}</small>}</td>
      <td><bdi className="catalog-price">{product.price} {product.currency}</bdi></td>
      <td>{productText(product.category, locale)}</td>
    </tr>)}</tbody></table>
  </div>;
}

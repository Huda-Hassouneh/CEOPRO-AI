import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { useEntitlements } from '../../billing/hooks/useEntitlements.js';
import BusinessPageContainer from '../../../shared/components/layout/BusinessPageContainer.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import { getApiErrorMessage } from '../../../shared/lib/apiErrorCore.js';
import { useCatalogProduct, useCatalogMutation } from '../hooks/useCatalog.js';
import { ProductForm } from '../components/ProductForm.jsx';
import { productText } from '../utils/productText.js';
import { ArrowLeft, Package, Pencil, Archive, RotateCcw, Wallet, Boxes, Barcode } from 'lucide-react';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Badge from '../../../shared/components/ui/Badge.jsx';
import RecordSummary from '../../../shared/components/ui/RecordSummary.jsx';
import '../catalog.css';
export function CatalogProductPage() {
  const { productId } = useParams(); const tenant = useAuthStore((state) => state.tenantId);
  return <CatalogProduct key={`${tenant}:${productId}`} id={productId} />;
}
function CatalogProduct({ id }) {
  const { t, locale } = useI18n(); const query = useCatalogProduct(id); const data = query.data; const product = data?.product;
  const update = useCatalogMutation('update'); const archive = useCatalogMutation('archive'); const restore = useCatalogMutation('restore');
  const [editing, setEditing] = useState(null); const [confirming, setConfirming] = useState(false);
  const action = product?.archivedAt ? restore : archive;
  const { getFeatureState } = useEntitlements();
  const date = (value) => value ? new Date(value).toLocaleString(locale) : '—';
  const closeEdit = () => { if (!update.isPending) { setEditing(null); update.reset(); } };
  const closeConfirm = () => { if (!action.isPending) { setConfirming(false); action.reset(); } };
  return <BusinessPageContainer className="catalog-page">
    <Link className="catalog-back" to="/products"><ArrowLeft size={16} aria-hidden="true" />{t('catalog.back')}</Link>
    {query.isPending && <p role="status">{t('catalog.loading')}</p>}
    {query.isError && <div role="alert" className="catalog-error"><p>{getApiErrorMessage(query.error, t)}</p><Button onClick={() => query.refetch()}>{t('catalog.retry')}</Button></div>}
    {product && !query.isError && <>
      <div className="catalog-detail-hero"><span className="catalog-detail-icon" aria-hidden="true"><Package size={30} /></span><div className="catalog-detail-heading"><PageHeader title={productText(product.name, locale)} subtitle={product.sku ? `${t('catalog.fields.sku')}: ${product.sku}` : undefined} actions={data.canEdit && <div className="catalog-actions">{!product.archivedAt && <Button leadingIcon={<Pencil size={16} />} onClick={() => setEditing(product)}>{t('catalog.edit')}</Button>}<Button variant="outline" leadingIcon={product.archivedAt ? <RotateCcw size={16} /> : <Archive size={16} />} onClick={() => setConfirming(true)}>{t(product.archivedAt ? 'catalog.restore' : 'catalog.archive')}</Button></div>} /><Badge variant={product.archivedAt ? 'neutral' : 'light-success'}>{t(product.archivedAt ? 'catalog.archived' : 'catalog.active')}</Badge></div></div>
      <RecordSummary items={[
        {label:t('catalog.fields.price'),value:`${product.price} ${product.currency}`,icon:<Wallet size={21} />},
        {label:t('catalog.stock'),value:data.inventory.currentStock ?? t('catalog.unknown'),hint:t('catalog.inventoryHint'),icon:<Boxes size={21} />},
        {label:t('catalog.fields.gtin'),value:product.gtin || '—',hint:product.gtinDuplicate ? t('catalog.gtin.duplicate') : undefined,icon:<Barcode size={21} />}
      ]} />
      <section className="catalog-panel"><h2>{t('catalog.details')}</h2><dl className="catalog-facts">
        {['sku', 'gtin', 'price', 'costPrice', 'currency', 'brand', 'category', 'description'].map((field) => <div key={field}><dt>{t(`catalog.fields.${field}`)}</dt><dd>{['brand', 'category', 'description'].includes(field) ? productText(product[field], locale) : product[field] ?? '—'}</dd></div>)}
      </dl>{product.gtinDuplicate && <p role="status" className="catalog-note">{t('catalog.gtin.duplicate')}</p>}</section>
      <div className="catalog-detail-grid"><section className="catalog-panel"><h2>{t('catalog.inventory')}</h2><p>{t('catalog.stock')}: <strong>{data.inventory.currentStock ?? t('catalog.unknown')}</strong></p>
        <p>{t('catalog.inventoryHint')}</p>{data.inventory.reason && <p role="status">{t(`catalog.stockReasons.${data.inventory.reason}`)}</p>}
        {data.inventory.levels.length > 0 ? <div className="catalog-table-wrap"><table><thead><tr><th>{t('catalog.warehouse')}</th><th>{t('catalog.quantity')}</th><th>{t('catalog.updated')}</th></tr></thead><tbody>{data.inventory.levels.map((level) => <tr key={level.id}><td>{level.warehouse || '—'}</td><td>{level.quantity ?? '—'}</td><td>{date(level.updatedAt)}</td></tr>)}</tbody></table></div> : <p>{t('catalog.noInventory')}</p>}
        <Link to="/connect-data">{t('catalog.importInventory')}</Link>
      </section>
      <section className="catalog-panel"><h2>{t('catalog.priceHistory')}</h2><p>{t('catalog.historyHint')}</p>
        {data.priceHistory.length > 0 ? <div className="catalog-table-wrap"><table><thead><tr><th>{t('catalog.changed')}</th><th>{t('catalog.oldPrice')}</th><th>{t('catalog.newPrice')}</th></tr></thead><tbody>{data.priceHistory.map((row) => <tr key={row.id}><td>{date(row.changedAt)}</td><td dir="ltr">{row.oldPrice === null ? '—' : `${row.oldPrice} ${row.oldCurrency || t('catalog.unknownCurrency')}`}</td><td dir="ltr">{row.price} {row.currency}</td></tr>)}</tbody></table></div> : <p>{t('catalog.noHistory')}</p>}
      </section>
      </div>
      <div className="catalog-panel catalog-next-actions">{!product.archivedAt && getFeatureState('demand_prediction').included && <Link to={`/demand/products/${id}`}>{t('catalog.forecast')}</Link>}<Button disabled>{t('catalog.quickSale')}</Button><span>{t('catalog.quickSaleHint')}</span></div>
      <Modal isOpen={Boolean(editing) && data.canEdit && !product.archivedAt} onClose={closeEdit} title={t('catalog.edit')} closeLabel={t('catalog.cancel')} maxWidth="720px">
        {editing && <ProductForm key={`${editing.id}:${editing.version}`} product={editing} currencies={data.currencies} primaryCurrency={data.primaryCurrency} t={t} pending={update.isPending} error={update.isError ? getApiErrorMessage(update.error, t) : null} onCancel={closeEdit} onSubmit={(input) => update.mutate(input, { onSuccess: () => setEditing(null) })} />}
      </Modal>
      <Modal isOpen={confirming && data.canEdit} onClose={closeConfirm} title={t(product.archivedAt ? 'catalog.restore' : 'catalog.archive')} closeLabel={t('catalog.cancel')}>
        <p>{t(product.archivedAt ? 'catalog.restoreHint' : 'catalog.archiveHint')}</p>
        {action.isError && <p role="alert" className="catalog-error">{getApiErrorMessage(action.error, t)}</p>}
        <div className="catalog-actions"><Button disabled={action.isPending} onClick={() => action.mutate({ id, expectedVersion: product.version }, { onSuccess: () => setConfirming(false) })}>{t(action.isPending ? 'catalog.saving' : product.archivedAt ? 'catalog.restore' : 'catalog.archive')}</Button><Button variant="outline" disabled={action.isPending} onClick={closeConfirm}>{t('catalog.cancel')}</Button></div>
      </Modal>
    </>}
  </BusinessPageContainer>;
}

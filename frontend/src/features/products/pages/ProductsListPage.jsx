import { useEffect, useMemo, useState } from 'react';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { MoreHorizontal, Plus, Search, ShoppingCart, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { hasAnyRole } from '../../auth/permissions/rolePermissions.js';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import PageHeader from '../../../shared/components/layout/PageHeader.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Toast from '../../../shared/components/ui/Toast.jsx';
import { ApexButton, Delta, Pager, Panel, Pill, StateBlock } from '../../../shared/components/apex/Apex.jsx';
import { useDebounce } from '../../../shared/hooks/useDebounce.js';
import { QuickSaleModal } from '../components/QuickSaleModal.jsx';
import { QuickAddProductModal } from '../components/QuickAddProductModal.jsx';
import { productsApi } from '../api/productsApi.js';
import { useDeleteProduct } from '../hooks/useDeleteProduct.js';
import { useDemandOverview } from '../../forecasting/hooks/useDemandOverview.js';
import '../styles/Products.css';

const PAGE_SIZE = 25;
const TREND_TONE = { increasing: 'success', decreasing: 'danger', stable: 'neutral' };
const ACTION_TONE = { restock: 'warning', reduce: 'violet', monitor: 'success' };

export function ProductsListPage() {
  const { t, locale, dir } = useI18n();
  const roles = useAuthStore((state) => state.roles);
  const canManageCatalog = hasAnyRole(roles, ['owner', 'admin']);
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const term = useDebounce(search.trim(), 300);
  useEffect(() => setPage(0), [term]);

  // Server-side search and paging: every product is reachable, however
  // large the catalog (the old list only ever loaded the first 50).
  const query = useQuery({
    queryKey: ['products', 'page', term, page],
    queryFn: () => productsApi.list({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, search: term || undefined }),
    placeholderData: keepPreviousData,
  });
  // Sales, demand and stock advice for each product (same data as Demand).
  const intelligence = useDemandOverview();
  const byId = useMemo(() => new Map((intelligence.data?.products ?? []).map((p) => [p.product_id, p])), [intelligence.data]);

  const deleteMutation = useDeleteProduct();
  const [quickSaleProduct, setQuickSaleProduct] = useState(null);
  const [pickingSaleProduct, setPickingSaleProduct] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [menuFor, setMenuFor] = useState(null);
  const [addingProduct, setAddingProduct] = useState(false);
  const [notice, setNotice] = useState(null);
  const showNotice = (variant, message) => setNotice({ variant, message });

  const number = useMemo(() => new Intl.NumberFormat(locale, { maximumFractionDigits: 1 }), [locale]);
  const currencyFormatter = (amount, currency) => (amount == null || !currency ? t('products.common.notAvailable') : new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amount));

  const products = query.data?.products ?? [];
  const total = query.data?.total ?? 0;

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteMutation.mutateAsync(deleteTarget.product_id);
      showNotice('success', t('products.list.deleted', { name: deleteTarget.product_name }));
      setDeleteTarget(null);
    } catch {
      showNotice('error', t('products.list.deleteFailed'));
    }
  };

  const openProduct = (product) => navigate(routePaths.productDetail.replace(':productId', product.product_id));

  return (
    <DashboardLayout>
      <div className="products-page apex-page" dir={dir}>
        <PageHeader
          title={t('products.page.title')}
          subtitle={t('productsApex.subtitle')}
          actions={(
            <>
              <ApexButton variant="secondary" onClick={() => navigate('/catalog')}>{t('catalog.title')}</ApexButton>
              <ApexButton variant="secondary" icon={ShoppingCart} onClick={() => setPickingSaleProduct(true)}>{t('productsApex.recordSale')}</ApexButton>
              <ApexButton variant="secondary" icon={Upload} onClick={() => navigate(routePaths.connectData)}>{t('productsApex.importSales')}</ApexButton>
              {canManageCatalog && <ApexButton icon={Plus} onClick={() => setAddingProduct(true)}>{t('products.list.addProduct')}</ApexButton>}
            </>
          )}
        />

        <Panel
          title={query.isSuccess ? t('productsApex.count', { count: number.format(total) }) : t('products.page.title')}
          actions={(
            <label className="apex-search">
              <Search size={16} aria-hidden="true" />
              <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('products.list.searchPlaceholder')} aria-label={t('products.list.searchPlaceholder')} />
            </label>
          )}
          bodyClassName="is-flush"
        >
          {query.isPending && <div style={{ padding: '0 22px 22px' }}><StateBlock kind="loading" title={t('common.loading')} /></div>}
          {query.isError && <StateBlock kind="error" title={t('products.list.loadError')} onRetry={() => query.refetch()} retryLabel={t('products.list.retry')} />}
          {query.isSuccess && products.length === 0 && (
            <StateBlock
              title={t(term ? 'products.list.noResultsTitle' : 'products.list.emptyTitle')}
              description={t(term ? 'products.list.noResultsDescription' : 'products.list.emptyDescription')}
              action={!term && <>{canManageCatalog && <ApexButton icon={Plus} onClick={() => setAddingProduct(true)}>{t('products.list.addProduct')}</ApexButton>}<ApexButton variant="secondary" icon={Upload} onClick={() => navigate(routePaths.connectData)}>{t('productsApex.importProducts')}</ApexButton></>}
            />
          )}
          {query.isSuccess && products.length > 0 && (
            <div className="apex-table-wrap">
              <table className="apex-table products-apex-table">
                <thead>
                  <tr>
                    <th>{t('products.list.columns.name')}</th>
                    <th className="apex-table__num">{t('products.list.columns.price')}</th>
                    <th className="apex-table__num">{t('productsApex.sold30')}</th>
                    <th>{t('productsApex.demand')}</th>
                    <th className="apex-table__num">{t('products.list.columns.stock')}</th>
                    <th>{t('productsApex.advice')}</th>
                    <th><span className="sr-only">{t('products.list.columns.actions')}</span></th>
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => {
                    const intel = byId.get(product.product_id);
                    return (
                      <tr key={product.product_id}>
                        <td>
                          <button type="button" className="apex-table__link" onClick={() => openProduct(product)}>{product.product_name}</button>
                          <div className="apex-muted products-apex-sub">{[product.category, product.brand].filter(Boolean).join(' · ')}</div>
                        </td>
                        <td className="apex-table__num apex-table__primary">{currencyFormatter(product.current_price, product.currency)}</td>
                        <td className="apex-table__num">
                          {intel ? number.format(intel.sold_last_30) : '—'}
                          {intel?.sales_change_pct != null && intel.sold_previous_30 >= 5 && <div><Delta value={intel.sales_change_pct} /></div>}
                        </td>
                        <td>{intel?.forecast_next_30 != null ? <Pill tone={TREND_TONE[intel.trend] || 'neutral'}>{t(`demandApex.trend.${intel.trend}`)}</Pill> : <span className="apex-muted">{intel?.last_sale_at ? t('demandApex.table.calculating') : t('productsApex.noSales')}</span>}</td>
                        <td className="apex-table__num">{product.stock_quantity == null ? <span className="apex-muted">{t('demandApex.table.notTracked')}</span> : <span className={product.stock_quantity <= 0 ? 'apex-down' : ''}>{number.format(product.stock_quantity)}</span>}</td>
                        <td>{intel && intel.forecast_next_30 != null && ACTION_TONE[intel.stock_action] ? <Pill tone={ACTION_TONE[intel.stock_action]}>{t(`demandApex.action.${intel.stock_action}`)}</Pill> : <span className="apex-muted">—</span>}</td>
                        <td className="products-apex-actions">
                          <ApexButton size="sm" variant="ghost" icon={ShoppingCart} onClick={() => setQuickSaleProduct(product)} aria-label={t('productsApex.sellFor', { name: product.product_name })}>{t('productsApex.sell')}</ApexButton>
                          <div className="apex-menu">
                            <button type="button" className="apex-icon-btn" aria-haspopup="menu" aria-expanded={menuFor === product.product_id} aria-label={t('productsApex.moreFor', { name: product.product_name })} onClick={() => setMenuFor(menuFor === product.product_id ? null : product.product_id)}><MoreHorizontal size={16} /></button>
                            {menuFor === product.product_id && (
                              <div className="apex-menu__list" role="menu" onMouseLeave={() => setMenuFor(null)}>
                                <button type="button" role="menuitem" onClick={() => { setMenuFor(null); openProduct(product); }}>{t('productsApex.open')}</button>
                                {canManageCatalog && <button type="button" role="menuitem" onClick={() => { setMenuFor(null); navigate(routePaths.productEdit.replace(':productId', product.product_id)); }}>{t('products.common.edit')}</button>}
                                {canManageCatalog && <button type="button" role="menuitem" className="is-danger" onClick={() => { setMenuFor(null); setDeleteTarget(product); }}>{t('products.common.delete')}</button>}
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          {query.isSuccess && <Pager page={page} pageSize={PAGE_SIZE} total={total} onChange={setPage} t={t} dir={dir} number={number} busy={query.isFetching} />}
        </Panel>

        <SaleProductPicker open={pickingSaleProduct} onClose={() => setPickingSaleProduct(false)} onPick={(product) => { setPickingSaleProduct(false); setQuickSaleProduct(product); }} t={t} currencyFormatter={currencyFormatter} />
        <QuickSaleModal open={Boolean(quickSaleProduct)} product={quickSaleProduct} onClose={() => setQuickSaleProduct(null)} currencyFormatter={currencyFormatter} t={t} onNotice={showNotice} />
        {canManageCatalog && <QuickAddProductModal open={addingProduct} onClose={() => setAddingProduct(false)} onCreated={() => showNotice('success', t('products.list.added'))} t={t} />}
        {canManageCatalog && <Modal isOpen={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} title={t('products.deleteConfirm.title')} closeLabel={t('common.close')} maxWidth="420px" footer={<>
          <Button variant="outline" onClick={() => setDeleteTarget(null)}>{t('products.common.cancel')}</Button>
          <Button className="products-danger-button" onClick={confirmDelete} loading={deleteMutation.isPending} loadingLabel={t('products.common.saving')}>{t('products.deleteConfirm.confirm')}</Button>
        </>}>
          <p>{t('products.deleteConfirm.message', { name: deleteTarget?.product_name })}</p>
        </Modal>}
        {notice && <div className="products-toast"><Toast variant={notice.variant} message={notice.message} onClose={() => setNotice(null)} /></div>}
      </div>
    </DashboardLayout>
  );
}

// "Record sale" from the Products header: find the product, then the
// same Quick Sale dialog as each row uses.
function SaleProductPicker({ open, onClose, onPick, t, currencyFormatter }) {
  const [search, setSearch] = useState('');
  const term = useDebounce(search.trim(), 250);
  const query = useQuery({
    queryKey: ['products', 'picker', term],
    queryFn: () => productsApi.list({ limit: 8, search: term || undefined }),
    enabled: open,
  });
  useEffect(() => { if (open) setSearch(''); }, [open]);
  return (
    <Modal isOpen={open} onClose={onClose} title={t('productsApex.pickTitle')} closeLabel={t('common.close')} maxWidth="520px">
      <label className="apex-search apex-search--block">
        <Search size={16} aria-hidden="true" />
        <input autoFocus type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder={t('sales.record.productPlaceholder')} aria-label={t('sales.record.productPlaceholder')} />
      </label>
      <ul className="apex-pick-list">
        {query.isPending && <li className="apex-muted">{t('common.loading')}</li>}
        {query.isSuccess && query.data.products.length === 0 && <li className="apex-muted">{t('products.list.noResultsTitle')}</li>}
        {query.data?.products?.map((product) => (
          <li key={product.product_id}>
            <button type="button" onClick={() => onPick(product)}>
              <span>{product.product_name}</span>
              <span className="apex-muted">{currencyFormatter(product.current_price, product.currency)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

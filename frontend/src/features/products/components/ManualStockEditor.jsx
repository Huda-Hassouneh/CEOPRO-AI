import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import Button from '../../../shared/components/ui/Button.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import { productsApi } from '../api/productsApi.js';
import '../styles/Products.css';

/** Writes only tenant-owned manual canonical inventory through the existing
 * product API. M96 provider observations remain separate source evidence. */
export function ManualStockEditor({ productId, inventory, t }) {
  const queryClient = useQueryClient();
  const [values, setValues] = useState({
    stock_quantity: inventory?.stock_quantity ?? '',
    reorder_level: inventory?.reorder_level ?? '',
    safety_stock: inventory?.safety_stock ?? '',
  });
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);
  const mutation = useMutation({
    mutationFn: productsApi.updateInventory,
    onSuccess: async (result) => {
      setValues({ stock_quantity: result.stock_quantity, reorder_level: result.reorder_level, safety_stock: result.safety_stock });
      setError(null);
      setSaved(true);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['product', productId] }),
        queryClient.invalidateQueries({ queryKey: ['products'] }),
        queryClient.invalidateQueries({ queryKey: ['product-intelligence', productId] }),
      ]);
    },
    onError: () => { setSaved(false); setError(t('products.inventory.saveError')); },
  });

  const set = (field) => (event) => { setValues({ ...values, [field]: event.target.value }); setSaved(false); };
  const validQuantity = (value) => value === '' || (
    Number.isFinite(Number(value)) && Number(value) >= 0 &&
    /^\d{1,10}(?:\.\d{1,4})?$/.test(value)
  );

  return <section className="products-form-card" aria-labelledby="manual-stock-title">
    <h2 id="manual-stock-title">{t('products.inventory.title')}</h2>
    <p className="products-inline-help">{t('products.inventory.sourceBoundary')}</p>
    {error && <p className="products-inline-error" role="alert">{error}</p>}
    {saved && <p className="products-inline-success" role="status">{t('products.inventory.saved')}</p>}
    <form className="products-form" onSubmit={(event) => {
      event.preventDefault();
      if (!validQuantity(values.stock_quantity) || values.stock_quantity === ''
          || !validQuantity(values.reorder_level) || !validQuantity(values.safety_stock)) {
        setError(t('products.inventory.stockInvalid'));
        setSaved(false);
        return;
      }
      setError(null);
      mutation.mutate({
        id: productId,
        stock_quantity: Number(values.stock_quantity),
        ...(values.reorder_level !== '' ? { reorder_level: Number(values.reorder_level) } : {}),
        ...(values.safety_stock !== '' ? { safety_stock: Number(values.safety_stock) } : {}),
      });
    }}>
      <div className="products-form-grid">
        <Input type="number" min="0" step="0.0001" required label={t('products.inventory.quantity')} value={values.stock_quantity} onChange={set('stock_quantity')} disabled={mutation.isPending} />
        <Input type="number" min="0" step="0.0001" label={t('products.inventory.reorder')} value={values.reorder_level} onChange={set('reorder_level')} disabled={mutation.isPending} />
        <Input type="number" min="0" step="0.0001" label={t('products.inventory.safety')} value={values.safety_stock} onChange={set('safety_stock')} disabled={mutation.isPending} />
      </div>
      <div className="products-form-actions">
        <Button type="submit" disabled={mutation.isPending} loading={mutation.isPending} loadingLabel={t('products.common.saving')}>
          {t('products.inventory.save')}
        </Button>
      </div>
    </form>
  </section>;
}

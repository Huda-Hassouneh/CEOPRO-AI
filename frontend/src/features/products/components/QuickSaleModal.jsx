import { useEffect, useState } from 'react';
import Modal from '../../../shared/components/ui/Modal.jsx';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { useQuickSale } from '../hooks/useQuickSale.js';
import { useSubmitLock } from '../../../shared/hooks/useSubmitLock.js';

// backend/src/ai/routers/sales.py's POST /sales/quick-sale - writes one
// real invoice+invoice_item immediately. unit_price is optional
// server-side (defaults to the product's own current_price when
// omitted) - left blank here does exactly that, never a guessed value.
export function QuickSaleModal({ open, product, onClose, currencyFormatter, t, onNotice }) {
  const [quantity, setQuantity] = useState('1');
  const [unitPrice, setUnitPrice] = useState('');
  const mutation = useQuickSale();
  const runLocked = useSubmitLock();

  useEffect(() => {
    if (open) { setQuantity('1'); setUnitPrice(''); mutation.reset(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, product?.product_id]);

  if (!product) return null;

  const submit = async (event) => {
    event.preventDefault();
    const qty = Number(quantity);
    if (!qty || qty <= 0 || mutation.isPending) return;
    try {
      const result = await runLocked(() => mutation.mutateAsync({
        productId: product.product_id,
        quantity: qty,
        unitPrice: unitPrice !== '' ? Number(unitPrice) : undefined,
      }));
      if (result === undefined) return; // a second click while the first sale is being recorded
      onNotice('success', t('products.quickSale.recorded', { invoice: result.sale.invoice_number }));
      onClose();
    } catch (error) {
      onNotice('error', error?.response?.status === 409 ? t('sales.record.insufficientStock') : t('products.quickSale.failed'));
    }
  };

  return <Modal isOpen={open} onClose={onClose} title={t('products.quickSale.title')} closeLabel={t('common.close')} maxWidth="480px" footer={<>
    <Button variant="outline" onClick={onClose}>{t('products.common.cancel')}</Button>
    <Button onClick={submit} loading={mutation.isPending} loadingLabel={t('products.common.saving')}>{t('products.quickSale.record')}</Button>
  </>}>
    <form className="products-quick-sale-form" onSubmit={submit}>
      <p className="products-quick-sale-product"><strong>{product.product_name}</strong><span>{currencyFormatter(product.current_price, product.currency)}</span></p>
      <Input type="number" min="0" step="any" label={t('products.quickSale.quantity')} value={quantity} onChange={(event) => setQuantity(event.target.value)} disabled={mutation.isPending} />
      <Input type="number" min="0" step="any" label={t('products.quickSale.unitPrice')} value={unitPrice} onChange={(event) => setUnitPrice(event.target.value)} hint={t('products.quickSale.unitPriceHint')} disabled={mutation.isPending} />
    </form>
  </Modal>;
}

import Modal from '../../../shared/components/ui/Modal.jsx';
import { ProductForm } from './ProductForm.jsx';
import { useCreateProduct } from '../hooks/useCreateProduct.js';

// The simple path for a tenant with no POS/ERP/live integration: add a
// product (name + price, quantity optional) without leaving the Products
// list or navigating to the full /products/new page. Reuses ProductForm/
// useCreateProduct exactly as ProductFormPage.jsx does - same validation,
// same POST /products call, same 'products' query invalidation - this is
// only a lighter entry point, not a second product-creation path.
// ProductFormPage.jsx and its route stay in place for edit and for
// anyone who prefers the full page.
export function QuickAddProductModal({ open, onClose, onCreated, t }) {
  const createMutation = useCreateProduct();

  const submit = async (payload) => {
    try {
      await createMutation.mutateAsync(payload);
      onCreated?.();
      onClose();
    } catch {
      // mutation.isError renders below; stay open so the user can retry.
    }
  };

  return <Modal isOpen={open} onClose={onClose} title={t('products.form.createTitle')} closeLabel={t('common.close')} maxWidth="560px">
    <ProductForm mode="create" onSubmit={submit} submitting={createMutation.isPending} error={createMutation.isError ? t('products.form.saveError') : null} t={t} />
  </Modal>;
}

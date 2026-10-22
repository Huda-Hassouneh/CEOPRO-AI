import { ArrowLeft } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { useI18n } from '../../../app/providers/I18nProvider.jsx';
import { useAuthStore } from '../../auth/store/authStore.js';
import { hasAnyRole } from '../../auth/permissions/rolePermissions.js';
import { DashboardLayout } from '../../../app/layouts/DashboardLayout.jsx';
import { routePaths } from '../../../app/router/routePaths.js';
import Skeleton from '../../../shared/components/ui/Skeleton.jsx';
import EmptyState from '../../../shared/components/ui/EmptyState.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { ProductForm } from '../components/ProductForm.jsx';
import { ManualStockEditor } from '../components/ManualStockEditor.jsx';
import { useProduct } from '../hooks/useProduct.js';
import { useCreateProduct } from '../hooks/useCreateProduct.js';
import { useUpdateProduct } from '../hooks/useUpdateProduct.js';
import '../styles/Products.css';

// product_name/brand/category are real JSONB {locale: text} dicts
// server-side (products.py::get_product returns every locale) - resolved
// to a single "en" value here to match ProductForm's single-locale
// fields (see that component's own note on why: a full per-locale editor
// is separate, larger scope).
function localizedText(value) {
  if (!value) return '';
  if (typeof value === 'string') return value;
  return value.en || value.ar || Object.values(value)[0] || '';
}

export function ProductFormPage() {
  const { t } = useI18n();
  const roles = useAuthStore((state) => state.roles);
  const canManageCatalog = hasAnyRole(roles, ['owner', 'admin']);
  const navigate = useNavigate();
  const { productId } = useParams();
  const isEdit = Boolean(productId);
  const productQuery = useProduct(productId);
  const createMutation = useCreateProduct();
  const updateMutation = useUpdateProduct();
  const mutation = isEdit ? updateMutation : createMutation;

  if (!canManageCatalog) {
    return <DashboardLayout><div className="products-page"><EmptyState title={t('products.form.restricted')} action={<Button size="sm" variant="outline" onClick={() => navigate(routePaths.products)}>{t('products.form.back')}</Button>} /></div></DashboardLayout>;
  }

  const goBack = () => navigate(routePaths.products);

  const submit = async (payload) => {
    try {
      if (isEdit) await updateMutation.mutateAsync({ id: productId, ...payload });
      else await createMutation.mutateAsync(payload);
      goBack();
    } catch {
      // mutation.error already renders below; stay on the form.
    }
  };

  let initialValues;
  if (isEdit) {
    if (productQuery.isPending) return <DashboardLayout><div className="products-page"><Skeleton height="360px" variant="rectangular" /></div></DashboardLayout>;
    if (productQuery.isError || !productQuery.data?.product) {
      return <DashboardLayout><div className="products-page"><EmptyState title={t('products.form.notFound')} action={<Button size="sm" variant="outline" onClick={goBack}>{t('products.form.back')}</Button>} /></div></DashboardLayout>;
    }
    const product = productQuery.data.product;
    initialValues = {
      name: localizedText(product.product_name),
      brand: localizedText(product.brand),
      category: localizedText(product.category),
      currentPrice: product.current_price,
      costPrice: product.cost_price ?? '',
      currency: product.currency,
    };
  }

  return <DashboardLayout><div className="products-page products-form-page">
    <button type="button" className="products-back-link" onClick={goBack}><ArrowLeft size={15} />{t('products.form.back')}</button>
    <section className="products-form-card">
      <h1>{t(isEdit ? 'products.form.editTitle' : 'products.form.createTitle')}</h1>
      <ProductForm
        mode={isEdit ? 'edit' : 'create'}
        initialValues={initialValues}
        onSubmit={submit}
        submitting={mutation.isPending}
        error={mutation.isError ? t('products.form.saveError') : null}
        t={t}
      />
    </section>
    {isEdit && <ManualStockEditor productId={productId} inventory={productQuery.data.product.inventory} t={t} />}
  </div></DashboardLayout>;
}

import { useEffect, useRef, useState } from 'react';
import Input from '../../../shared/components/ui/Input.jsx';
import Button from '../../../shared/components/ui/Button.jsx';
import { useSubmitLock } from '../../../shared/hooks/useSubmitLock.js';
import { useCompany } from '../../settings/hooks/useCompany.js';

// Mirrors backend/src/ai/routers/products.py's real ProductCreateRequest/
// ProductUpdateRequest exactly: product_name must carry a non-empty "en"
// key, current_price >= 0 required, currency is a 3-letter uppercase
// code, cost_price/brand/category/initial_stock_quantity are all
// optional. Single-locale (English only) for now - product_name/brand/
// category are real JSONB {locale: text} dicts server-side, but a full
// per-locale editor is separate, larger scope (MultilingualFieldEditor.jsx).
export function ProductForm({ mode = 'create', initialValues, onSubmit, submitting, error, t }) {
  const [values, setValues] = useState({
    name: initialValues?.name || '',
    brand: initialValues?.brand || '',
    category: initialValues?.category || '',
    currentPrice: initialValues?.currentPrice ?? '',
    costPrice: initialValues?.costPrice ?? '',
    currency: initialValues?.currency || 'JOD',
    initialStock: initialValues?.initialStock ?? '',
  });
  const [fieldErrors, setFieldErrors] = useState({});
  const runLocked = useSubmitLock();
  const currencyTouchedRef = useRef(Boolean(initialValues?.currency));
  const update = (key) => (event) => {
    if (key === 'currency') currencyTouchedRef.current = true;
    setValues({ ...values, [key]: event.target.value });
    // An error is about the old value; editing the field clears it.
    if (fieldErrors[key]) setFieldErrors(({ [key]: _cleared, ...rest }) => rest);
  };

  // A new product defaults to the company's own primary currency (what
  // the tenant actually bills in), not a hard-coded JOD - a Moroccan or
  // French tenant would otherwise have every product silently priced in
  // the wrong currency unless they noticed and retyped it. Only applied
  // while the user hasn't edited the field themselves.
  const companyQuery = useCompany();
  const companyCurrency = companyQuery.data?.company?.currency;
  useEffect(() => {
    if (mode !== 'create' || currencyTouchedRef.current || !companyCurrency) return;
    setValues((current) => ({ ...current, currency: companyCurrency }));
  }, [mode, companyCurrency]);

  const validate = () => {
    const errors = {};
    if (!values.name.trim()) errors.name = t('products.form.errors.nameRequired');
    if (values.currentPrice === '' || Number(values.currentPrice) < 0) errors.currentPrice = t('products.form.errors.priceInvalid');
    if (!/^[A-Z]{3}$/.test(values.currency.trim().toUpperCase())) errors.currency = t('products.form.errors.currencyInvalid');
    if (values.costPrice !== '' && Number(values.costPrice) < 0) errors.costPrice = t('products.form.errors.priceInvalid');
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const submit = (event) => {
    event.preventDefault();
    if (submitting || !validate()) return;
    runLocked(() => onSubmit({
      product_name: { en: values.name.trim() },
      brand: values.brand.trim() ? { en: values.brand.trim() } : undefined,
      category: values.category.trim() ? { en: values.category.trim() } : undefined,
      current_price: Number(values.currentPrice),
      cost_price: values.costPrice !== '' ? Number(values.costPrice) : undefined,
      currency: values.currency.trim().toUpperCase(),
      ...(mode === 'create' ? { initial_stock_quantity: values.initialStock !== '' ? Number(values.initialStock) : undefined } : {}),
    }));
  };

  return <form className="products-form" onSubmit={submit}>
    {error && <p className="products-inline-error" role="alert">{error}</p>}
    <div className="products-form-grid">
      <Input label={t('products.form.name')} value={values.name} onChange={update('name')} error={fieldErrors.name} disabled={submitting} />
      <Input label={t('products.form.brand')} value={values.brand} onChange={update('brand')} disabled={submitting} />
      <Input label={t('products.form.category')} value={values.category} onChange={update('category')} disabled={submitting} />
      <Input label={t('products.form.currency')} value={values.currency} onChange={update('currency')} error={fieldErrors.currency} hint={t('products.form.currencyHint')} disabled={submitting} />
      <Input type="number" min="0" step="any" label={t('products.form.currentPrice')} value={values.currentPrice} onChange={update('currentPrice')} error={fieldErrors.currentPrice} disabled={submitting} />
      <Input type="number" min="0" step="any" label={t('products.form.costPrice')} value={values.costPrice} onChange={update('costPrice')} error={fieldErrors.costPrice} hint={t('products.form.costPriceHint')} disabled={submitting} />
      {mode === 'create' && <Input type="number" min="0" step="any" label={t('products.form.initialStock')} value={values.initialStock} onChange={update('initialStock')} hint={t('products.form.initialStockHint')} disabled={submitting} />}
    </div>
    <div className="products-form-actions">
      <Button type="submit" disabled={submitting} loading={submitting} loadingLabel={t('products.common.saving')}>
        {t(mode === 'create' ? 'products.form.create' : 'products.form.save')}
      </Button>
    </div>
  </form>;
}

import { validGtin } from '../utils/gtin.js';
import { useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
const text = (value) => typeof value === 'string' ? { en: value, ar: '' } : { en: value?.en || value?.name || '', ar: value?.ar || '' };
export function ProductForm({ product, currencies = [], primaryCurrency, pending = false, error, onSubmit, onCancel, t }) {
  const [form, setForm] = useState(() => ({ name: text(product?.name), sku: product?.sku || '', gtin: product?.gtin || '', price: product?.price ?? '', costPrice: product?.costPrice ?? '',
    currency: product?.currency || primaryCurrency || currencies[0] || '', brand: text(product?.brand), category: text(product?.category), description: text(product?.description) }));
  const [gtinError,setGtinError]=useState(false);
  const set = (key, value) => setForm((state) => ({ ...state, [key]: value }));
  const localized = (key, length) => <fieldset className="catalog-localized" disabled={pending}>
    <legend>{t(`catalog.fields.${key}`)}</legend>
    {['en', 'ar'].map((lang) => <label key={lang}>{t(`catalog.languages.${lang}`)}
      <input dir={lang === 'ar' ? 'rtl' : 'ltr'} maxLength={length} value={form[key][lang]} onChange={(event) => set(key, { ...form[key], [lang]: event.target.value })} />
    </label>)}
  </fieldset>;
  return <form className="catalog-form" onSubmit={(event) => {
    event.preventDefault(); if (pending) return;
    if(form.gtin.trim() && !validGtin(form.gtin.trim())){setGtinError(true);return;}
    setGtinError(false);
    onSubmit({ ...form, sku: form.sku.trim() || null, gtin: form.gtin.trim() || null, costPrice: form.costPrice === '' ? null : form.costPrice,
      ...(product ? { id: product.id, expectedVersion: product.version } : {}) });
  }}>
    {error && <p role="alert" className="catalog-error">{error}</p>}
    {localized('name', 250)}
    <p className="catalog-note">{t('catalog.nameHint')}</p>
    <div className="catalog-field-grid">
      <label>{t('catalog.fields.sku')}<input disabled={pending} dir="ltr" maxLength={100} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,99}" value={form.sku} onChange={(event) => set('sku', event.target.value)} /></label>
      <label>{t('catalog.fields.gtin')}<input disabled={pending} dir="ltr" type="text" inputMode="numeric" maxLength={14} pattern="(?:[0-9]{8}|[0-9]{12}|[0-9]{13}|[0-9]{14})" aria-invalid={gtinError} aria-describedby="product-gtin-hint" value={form.gtin} onChange={event=>{set('gtin',event.target.value);setGtinError(false);}} /><small id="product-gtin-hint">{t('catalog.gtin.hint')}</small>{gtinError && <span role="alert" className="catalog-error">{t('catalog.gtin.invalid')}</span>}</label>
      <label>{t('catalog.fields.currency')}<select disabled={pending} required value={form.currency} onChange={(event) => setForm((state) => ({ ...state, currency: event.target.value, price: '', costPrice: '' }))}>
        <option value="">{t('catalog.selectCurrency')}</option>{[...new Set([...currencies, product?.currency].filter(Boolean))].map((currency) => <option key={currency}>{currency}</option>)}
      </select></label>
      <label>{t('catalog.fields.price')}<input disabled={pending} required dir="ltr" inputMode="decimal" pattern="(?:0|[1-9][0-9]{0,7})(?:[.][0-9]{1,4})?" value={form.price} onChange={(event) => set('price', event.target.value)} /></label>
      <label>{t('catalog.fields.costPrice')}<input disabled={pending} dir="ltr" inputMode="decimal" pattern="(?:0|[1-9][0-9]{0,7})(?:[.][0-9]{1,4})?" value={form.costPrice} onChange={(event) => set('costPrice', event.target.value)} /></label>
    </div>
    <p className="catalog-note">{t('catalog.currencyHint')}</p>
    {localized('brand', 150)}{localized('category', 150)}{localized('description', 4000)}
    <div className="catalog-actions"><Button type="submit" disabled={pending || !(form.name.en.trim() || form.name.ar.trim())}>{t(pending ? 'catalog.saving' : 'catalog.save')}</Button>
      <Button type="button" variant="outline" disabled={pending} onClick={onCancel}>{t('catalog.cancel')}</Button></div>
  </form>;
}

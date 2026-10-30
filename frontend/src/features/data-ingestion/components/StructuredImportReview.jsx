import { importSheetLabel } from '../../data-connections/utils/connectionPresentation.js';
import { useEffect, useMemo, useState } from 'react';
import Button from '../../../shared/components/ui/Button.jsx';
import { ingestionApi } from '../api/ingestionApi.js';
import { formatImportIssue } from '../utils/importIssueMessage.js';

function displayProduct(product, locale) {
  const names = product?.product_name;
  const name = typeof names === 'string' ? names : names?.[locale] || names?.en || names?.ar || '';
  const brand = product?.brand?.[locale] || product?.brand?.en;
  const price = product?.current_price != null ? `${product.current_price} ${product.currency}` : '';
  const created = product?.created_at ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(product.created_at)) : '';
  return [name, product?.sku, brand, price, created].filter(Boolean).join(' · ');
}

function ProductChoice({ match, value, onChange, primaryCurrency, canCreateProducts, locale, t }) {
  const [search, setSearch] = useState(match.productName || match.sku || '');
  const [products, setProducts] = useState(match.candidates);
  const [lookupError, setLookupError] = useState(false);

  useEffect(() => {
    if (match.status !== 'missing') return undefined;
    let active = true;
    const timer = setTimeout(async () => {
      try {
        const found = await ingestionApi.searchImportProducts(search);
        if (active) { setProducts(found); setLookupError(false); }
      } catch {
        if (active) setLookupError(true);
      }
    }, 300);
    return () => { active = false; clearTimeout(timer); };
  }, [match.status, search]);

  const options = match.status === 'ambiguous' ? match.candidates : products;
  const action = value?.action || '';
  return (
    <fieldset className="structured-import-choice">
      <legend>{importSheetLabel(match.sheet, t)}, {t('connectData.feedback.rowNumber', { row: match.row })}: {match.productName || match.sku}</legend>
      <p>{t(`connectData.review.status.${match.status}`)}</p>
      {match.status === 'conflict' ? (
        <p role="alert">{t('connectData.review.fixFile')}</p>
      ) : (
        <>
          <label>
            {t('connectData.review.action')}
            <select value={action} onChange={(event) => {
              const next = event.target.value;
              onChange(next === 'select' ? { action: 'select', productId: '' } :
                next === 'create' ? { action: 'create', price: '', currency: primaryCurrency, sku: match.sku || '' } : null);
            }}>
              <option value="">{t('connectData.review.chooseAction')}</option>
              <option value="select">{t('connectData.review.selectExisting')}</option>
              {canCreateProducts && match.status === 'missing' && match.productName && <option value="create">{t('connectData.review.createProduct')}</option>}
            </select>
          </label>
          {action === 'select' && (
            <>
              {match.status === 'missing' && <label>{t('connectData.review.searchCatalog')}
                <input value={search} onChange={(event) => {
                  setSearch(event.target.value);
                  onChange({ action: 'select', productId: '' });
                }} />
              </label>}
              <label>{t('connectData.review.product')}
                <select value={value.productId || ''} onChange={(event) => onChange({ action: 'select', productId: event.target.value })}>
                  <option value="">{t('connectData.review.chooseProduct')}</option>
                  {options.map((product) => <option value={product.product_id} key={product.product_id}>{displayProduct(product, locale)}</option>)}
                </select>
              </label>
              {lookupError && <p role="alert">{t('connectData.review.searchError')}</p>}
            </>
          )}
          {action === 'create' && <div className="structured-import-create">
            <label>{t('connectData.review.price')}
              <input type="text" inputMode="decimal" placeholder="0.0000" value={value.price} onChange={(event) => onChange({ ...value, price: event.target.value })} />
            </label>
            <label>{t('connectData.review.currency')}
              <input value={value.currency} maxLength={3} onChange={(event) => onChange({ ...value, currency: event.target.value.toUpperCase() })} />
            </label>
            <label>{t('connectData.review.sku')}
              <input value={value.sku || ''} disabled={Boolean(match.sku)} maxLength={100} onChange={(event) => onChange({ ...value, sku: event.target.value })} />
            </label>
          </div>}
        </>
      )}
    </fieldset>
  );
}

export function StructuredImportReview({ preview, choices, review, busy, onChoice, onReview, onConfirm, onCancel, locale, t }) {
  const unresolved = useMemo(() => {
    const groups = new Map();
    for (const match of preview.matches.filter((entry) => entry.status !== 'matched')) {
      const key = JSON.stringify([match.status, match.productName.trim().toLocaleLowerCase(), match.sku.trim().toLocaleLowerCase(), match.candidates.map((p) => p.product_id)]);
      if (!groups.has(key)) groups.set(key, match);
    }
    return [...groups.values()];
  }, [preview]);
  const allResolved = preview.issues.length === 0 && preview.matches.every((match) => {
    if (match.status === 'matched') return true;
    const choice = choices[match.key];
    if (match.status === 'conflict' || !choice) return false;
    return choice.action === 'select' ? Boolean(choice.productId) : Boolean(choice.price && choice.currency);
  });
  return <section className="structured-import-review" aria-labelledby="structured-import-heading">
    <header>
      <div>
        <h3 id="structured-import-heading">{t('connectData.review.title')}</h3>
        <p>{t('connectData.review.previewOnly')}</p>
      </div>
      <Button size="sm" variant="outline" disabled={busy} onClick={onCancel}>{t('connectData.review.cancel')}</Button>
    </header>
    <div className="structured-import-summary" aria-live="polite">
      <span>{t('connectData.review.sheets')}: {preview.sheets.map(sheet => importSheetLabel(sheet, t)).join(' · ')}</span>
      {preview.counts.invoices > 0 && <span>{t('connectData.review.invoices', { count: preview.counts.invoices })}</span>}
      {preview.counts.items > 0 && <span>{t('connectData.review.items', { count: preview.counts.items })}</span>}
      {preview.counts.inventory > 0 && <span>{t('connectData.review.balances', { count: preview.counts.inventory })}</span>}
      <span>{t('connectData.review.matched', { count: preview.counts.matched })}</span>
      {preview.counts.needsAttention > 0 && <span>{t('connectData.review.needsAttention', { count: preview.counts.needsAttention })}</span>}
    </div>
    {preview.issues.length > 0 && <div className="structured-import-errors" role="alert">
      <strong>{t('connectData.review.fileIssues')}</strong>
      <ul>{preview.issues.map((issue, index) => <li key={index}>{importSheetLabel(issue.sheet, t)}{issue.row ? `, ${t('connectData.feedback.rowNumber', { row: issue.row })}` : ''}: {formatImportIssue(issue.message, t, { fallback: t('connectData.review.issues.generic') })}</li>)}</ul>
      <p>{t('connectData.review.fixFile')}</p>
    </div>}
    {unresolved.length > 0 && <div className="structured-import-resolvers">
      <h4>{t('connectData.review.resolveTitle')}</h4>
      <p>{t('connectData.review.reuseChoice')}</p>
      {!preview.canCreateProducts && <p>{t('connectData.review.creationUnavailable')}</p>}
      {unresolved.map((match) => <ProductChoice key={match.key} match={match} value={choices[match.key]}
        onChange={(value) => onChoice(match, value)} primaryCurrency={preview.primaryCurrency} canCreateProducts={preview.canCreateProducts} locale={locale} t={t} />)}
    </div>}
    <div className="structured-import-actions">
      <Button size="sm" disabled={!allResolved || busy} loading={busy} onClick={onReview}>{t('connectData.review.reviewChanges')}</Button>
      {!allResolved && <small>{t('connectData.review.resolveFirst')}</small>}
    </div>
    {review && <div className="structured-import-confirm" aria-live="polite">
      <h4>{t('connectData.review.confirmTitle')}</h4>
      <p>{t('connectData.review.confirmSummary', { invoices: review.counts.invoices, items: review.counts.items, inventory: review.counts.inventory, products: review.counts.productsToCreate })}</p>
      {review.changes?.length > 0 && <div className="structured-import-change-list">
        <h5>{t('connectData.review.stockChanges')}</h5>
        <ul>{review.changes.map((change) => <li key={change.key}>
          <strong>{typeof change.productName === 'object' ? displayProduct({ product_name: change.productName }, locale) : change.productName}</strong>
          {' · '}{change.warehouse || t('connectData.review.defaultWarehouse')}{' · '}
          {change.previous == null ? t('connectData.review.newBalance', { next: change.next }) : t('connectData.review.replaceBalance', { previous: change.previous, next: change.next })}
        </li>)}</ul>
      </div>}
      <Button size="sm" disabled={busy} loading={busy} onClick={onConfirm}>{t('connectData.review.confirmImport')}</Button>
    </div>}
  </section>;
}

const issuePatterns = [
  [/Staged payload must be a JSON object/i, 'json'],
  [/product_name is required/i, 'productName'],
  [/quantity must be a positive integer/i, 'quantity'],
  [/sku must be a valid product reference/i, 'sku'],
  [/unit_price must be|amount_raw must be|total_price exceeds/i, 'saleAmount'],
  [/currency must be a 3-letter ISO/i, 'currency'],
  [/transaction_date must be/i, 'saleDate'],
  [/discount_pct must be between/i, 'discount'],
  [/SALE_ID_CONFLICT/i, 'saleConflict'],
  [/Existing sale reused by stable/i, 'saleReused'],
  [/active product limit has been reached/i, 'productCapacity'],
  [/Missing required columns/i, 'salesColumns'],
  [/product_name, sku, or legacy product_id/i, 'productReference'],
  [/existing product UUID|invalid product selection|active product belonging/i, 'productSelection'],
  [/refer to different products|conflicting new product details/i, 'productConflict'],
  [/No active product matches|Resolve this product/i, 'productMissing'],
  [/More than one active product/i, 'productAmbiguous'],
  [/SKU format|sku may contain/i, 'sku'],
  [/price, currency, and SKU|invalid product details/i, 'productDetails'],
  [/must use YYYY-MM-DD|calendar date|due_date cannot/i, 'date'],
  [/must be an integer/i, 'integer'],
  [/nonnegative amount|Line total exceeds|item totals must equal|total_amount must equal/i, 'amount'],
  [/Invoice Items refers to an invoice outside/i, 'invoiceReference'],
  [/invoice_number is missing|duplicated in this file|Invoice .* already exists|invoice number.*already exists/i, 'invoiceDuplicate'],
  [/Duplicate product|Two rows resolve|Duplicate inventory balances/i, 'duplicateBalance'],
  [/Currency .* not configured|currency must be a three-letter|Invalid payment_status/i, 'currency'],
  [/preview expired|saved preview is invalid/i, 'expired'],
  [/changed since preview|changed since review/i, 'changed'],
  [/workbook|worksheet|columns must match|spreadsheet could not be read/i, 'template'],
  [/formulas are not allowed/i, 'formula'],
  [/UTF-8|content does not match|Upload a nonempty CSV or XLSX/i, 'file']
];

export function formatImportIssue(message, t, { fallback } = {}) {
  const match = issuePatterns.find(([pattern]) => pattern.test(String(message || '')));
  return match ? t(`connectData.review.issues.${match[1]}`) : fallback ?? String(message || t('connectData.review.issues.generic'));
}

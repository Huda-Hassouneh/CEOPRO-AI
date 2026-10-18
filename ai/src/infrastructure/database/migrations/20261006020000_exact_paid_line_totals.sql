-- Found in first-customer acceptance testing (cross-checking dashboard
-- revenue against the source files): chk_total_price_consistent required
-- total_price = ROUND(quantity * unit_price, 4) with a 4-decimal unit
-- price, so a discounted line had to be "snapped" to the nearest product
-- that 4-decimal unit price can express. On large quantities that moved
-- the recorded amount away from what the customer actually paid (900 kg
-- of sheet steel at a 3-decimal JOD discount price: up to 0.045 JOD per
-- line; 0.32 JOD over 90 days for one B2B tenant). Revenue must equal the
-- money received, so total_price is now stored exactly as paid, and the
-- 4-decimal unit_price only has to reproduce it to within half a unit of
-- its last decimal per item.
ALTER TABLE invoice_items DROP CONSTRAINT chk_total_price_consistent;
ALTER TABLE invoice_items ADD CONSTRAINT chk_total_price_consistent
    CHECK (ABS(total_price - quantity * unit_price) <= quantity * 0.00005 + 0.00005);

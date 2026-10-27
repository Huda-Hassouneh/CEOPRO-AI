-- Quantity and unit_price are both scale 4; their exact product is scale 8.
-- The existing equality requires the residual at that same precision. For
-- 912.35 * 0.9614 and paid total 877.135, residual 0.00171000 cannot be
-- represented by numeric(12,4). Preserve all paid totals and existing values.
-- Remove the typmod rather than rescale historical rows: source ownership
-- hashes serialize existing Decimal scales. The unchanged exact equality
-- and quantity-relative bound still determine every permitted adjustment.
-- Default, NOT NULL, tenant ownership, RLS, grants and constraints stay intact.
ALTER TABLE public.invoice_items
    ALTER COLUMN rounding_adjustment TYPE numeric;

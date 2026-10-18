-- Real data-corruption bug found in first-customer acceptance testing:
-- quantities were INTEGER everywhere, so any business that sells by weight,
-- length, volume or time had its sales silently rounded on import - 2.5 kg
-- of tomatoes became 2, 1.5 consulting hours became 2, 12.75 m of fabric
-- became 13 - corrupting units, revenue and every forecast built on them.
-- Grocery, restaurants (by-weight produce), manufacturing (raw materials),
-- fuel, textiles and hourly services all sell fractional quantities.
--
-- NUMERIC(14,4) holds every integer the old columns held, unchanged.
-- chk_total_price_consistent compared total_price (4 dp) to an exact
-- quantity*unit_price product, which can need up to 8 dp once quantity is
-- fractional (2.5 x 1.2345 = 3.08625); it now compares against that
-- product rounded to the column's own 4 dp.
ALTER TABLE invoice_items DROP CONSTRAINT chk_total_price_consistent;
ALTER TABLE invoice_items ALTER COLUMN quantity TYPE NUMERIC(14, 4);
ALTER TABLE invoice_items ADD CONSTRAINT chk_total_price_consistent
    CHECK (total_price = ROUND(quantity * unit_price, 4));

ALTER TABLE transactions ALTER COLUMN quantity_sold TYPE NUMERIC(14, 4);

ALTER TABLE inventory ALTER COLUMN stock_quantity TYPE NUMERIC(14, 4);
ALTER TABLE inventory ALTER COLUMN reorder_level TYPE NUMERIC(14, 4);
ALTER TABLE inventory ALTER COLUMN safety_stock TYPE NUMERIC(14, 4);

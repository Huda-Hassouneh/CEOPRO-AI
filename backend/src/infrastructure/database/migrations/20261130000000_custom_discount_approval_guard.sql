-- Additive safeguard for new automatic approvals, including previews frozen
-- before this fix. Accepted quotations/subscriptions and manual approval stay
-- unchanged. Use frozen policy/cost/FX evidence, never today's mutable rates.
CREATE OR REPLACE FUNCTION public.billing_custom_guard_automatic_vendor_ratio()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    snapshot jsonb := NEW.pricing_snapshot;
    calculation jsonb := snapshot->'calculation';
    item jsonb;
    monthly_cost numeric := 0;
    units numeric;
    unit_cost numeric;
    multiplier numeric;
    reserve numeric;
    months numeric;
    revenue numeric;
    fx numeric;
    ratio numeric;
BEGIN
    IF calculation->'enforceVendorCostRatioFloor' = 'false'::jsonb THEN
        RETURN NEW;
    END IF;
    IF calculation->'enforceVendorCostRatioFloor' IS DISTINCT FROM 'true'::jsonb
       OR jsonb_typeof(calculation->'vendorBreakdown') IS DISTINCT FROM 'array'
       OR snapshot->'commercial'->>'currency' IS DISTINCT FROM 'JOD'
       OR snapshot->'payment'->>'currency' IS DISTINCT FROM 'USD'
       OR snapshot->'fx'->>'sourceCurrency' IS DISTINCT FROM 'USD'
       OR snapshot->'fx'->>'targetCurrency' IS DISTINCT FROM 'JOD' THEN
        RAISE EXCEPTION 'Automatic approval requires complete frozen vendor-cost evidence' USING ERRCODE='55000';
    END IF;
    months := (snapshot->'commercial'->>'months')::numeric;
    revenue := (snapshot->'payment'->>'amount')::numeric;
    fx := (snapshot->'fx'->>'rate')::numeric;
    ratio := (calculation->>'maxVendorCostRevenueRatio')::numeric;
    IF months IS NULL OR months NOT IN (1,3,6)
       OR snapshot->'commercial'->>'period' IS DISTINCT FROM
          (CASE months WHEN 1 THEN 'monthly' WHEN 3 THEN 'three-months' WHEN 6 THEN 'six-months' END)
       OR revenue IS NULL OR NOT (revenue > 0 AND revenue < 'Infinity'::numeric)
       OR fx IS NULL OR NOT (fx > 0 AND fx < 'Infinity'::numeric)
       OR ratio IS NULL OR NOT (ratio > 0 AND ratio <= 1) THEN
        RAISE EXCEPTION 'Automatic approval requires valid frozen revenue and term evidence' USING ERRCODE='55000';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(calculation->'vendorBreakdown') LOOP
        units := (item->>'estimatedUsage')::numeric;
        unit_cost := (item->>'normalizedUnitCost')::numeric;
        multiplier := (item->>'operationalMultiplier')::numeric;
        reserve := (item->>'variabilityReserve')::numeric;
        IF units IS NULL OR NOT (units >= 0 AND units < 'Infinity'::numeric)
           OR unit_cost IS NULL OR NOT (unit_cost >= 0 AND unit_cost < 'Infinity'::numeric)
           OR multiplier IS NULL OR NOT (multiplier > 0 AND multiplier < 'Infinity'::numeric)
           OR reserve IS NULL OR NOT (reserve >= 1 AND reserve < 'Infinity'::numeric) THEN
            RAISE EXCEPTION 'Automatic approval requires valid frozen vendor-cost evidence' USING ERRCODE='55000';
        END IF;
        monthly_cost := monthly_cost + units * unit_cost * multiplier * reserve;
    END LOOP;
    IF monthly_cost * months > revenue * fx * ratio THEN
        RAISE EXCEPTION 'Manual review required for final vendor-cost ratio' USING ERRCODE='55000';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'Automatic approval requires valid frozen vendor-cost evidence' USING ERRCODE='55000';
END;
$$;
REVOKE ALL ON FUNCTION public.billing_custom_guard_automatic_vendor_ratio() FROM PUBLIC;

DROP TRIGGER IF EXISTS billing_custom_automatic_vendor_ratio ON public.billing_custom_quote_revisions;
CREATE TRIGGER billing_custom_automatic_vendor_ratio
BEFORE UPDATE OF state ON public.billing_custom_quote_revisions
FOR EACH ROW WHEN (OLD.state = 'draft' AND NEW.state = 'approved'
                  AND NEW.approval_reference LIKE 'automatic:%')
EXECUTE FUNCTION public.billing_custom_guard_automatic_vendor_ratio();

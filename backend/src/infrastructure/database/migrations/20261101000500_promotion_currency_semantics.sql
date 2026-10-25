-- Original KEEL percentage coupons are currency agnostic. Currency is
-- required for fixed-amount coupons only; checkout still verifies any
-- explicitly bound currency against the selected plan price.
ALTER TABLE public.billing_promotions
    DROP CONSTRAINT IF EXISTS ck_billing_promotions_active_approval;

ALTER TABLE public.billing_promotions
    ADD CONSTRAINT ck_billing_promotions_active_approval
    CHECK (status <> 'active' OR COALESCE((
        approval_reference IS NOT NULL AND length(btrim(approval_reference)) > 0
        AND approved_by IS NOT NULL AND approved_at IS NOT NULL
        AND stripe_coupon_id IS NOT NULL AND stripe_promotion_code_id IS NOT NULL
        AND terms ?& ARRAY['discount_type','discount_value','starts_at','expires_at',
                           'max_uses','max_uses_per_tenant','invoice_scope',
                           'stripe_coupon_id','stripe_promotion_code_id']
        AND terms->>'stripe_coupon_id' = stripe_coupon_id
        AND terms->>'stripe_promotion_code_id' = stripe_promotion_code_id
        AND terms->>'discount_type' IN ('percent','fixed_amount')
        AND (terms->>'discount_value') ~ '^[0-9]+(\.[0-9]+)?$'
        AND (terms->>'discount_value')::numeric > 0
        AND (terms->>'discount_type' <> 'percent' OR (terms->>'discount_value')::numeric <= 100)
        AND (terms->>'discount_type' <> 'fixed_amount' OR (terms->>'currency') ~ '^[A-Z]{3}$')
        AND (terms->>'currency' IS NULL OR (terms->>'currency') ~ '^[A-Z]{3}$')
        AND terms->>'invoice_scope' = 'initial_subscription'
        AND (terms->'max_uses' = 'null'::jsonb OR (terms->>'max_uses') ~ '^[1-9][0-9]*$')
        AND (terms->'max_uses_per_tenant' = 'null'::jsonb OR (terms->>'max_uses_per_tenant') ~ '^[1-9][0-9]*$')
        AND (terms->'starts_at' = 'null'::jsonb OR (terms->>'starts_at')::timestamptz IS NOT NULL)
        AND (terms->'expires_at' = 'null'::jsonb OR (terms->>'expires_at')::timestamptz IS NOT NULL)
        AND (terms->'starts_at' = 'null'::jsonb OR terms->'expires_at' = 'null'::jsonb
             OR (terms->>'starts_at')::timestamptz < (terms->>'expires_at')::timestamptz)
    ), FALSE));

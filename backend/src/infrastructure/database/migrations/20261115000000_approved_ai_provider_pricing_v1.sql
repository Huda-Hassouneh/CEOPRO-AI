-- Approved AI provider pricing catalog v1 (owner approval: 2026-10-28).
-- Installation authority only: run through scripts/apply_migrations.py.
-- USD/provider token costs, NOT customer Credits or subscription prices.
-- Keep applied versions immutable; add a forward migration for a new version.
DO $catalog$
DECLARE
    v_version CONSTANT text := 'ai-provider-pricing-v1';
    v_source CONSTANT text := 'https://console.groq.com/docs/model/openai/gpt-oss-20b';
    v_placeholder CONSTANT text := 'Price not confirmed - set from console.groq.com/docs/models or a Groq invoice';
    v_entry record;
    v_old public.provider_cost_schedules%ROWTYPE;
    v_new public.provider_cost_schedules%ROWTYPE;
    v_outcome text;
    v_subject text;
BEGIN
    -- Serialize against other catalog runs and concurrent operator writes.
    -- No SECURITY DEFINER command or runtime privilege is added.
    LOCK TABLE public.provider_cost_schedules IN SHARE ROW EXCLUSIVE MODE;
    FOR v_entry IN
        SELECT * FROM (VALUES
            ('ai', 'groq', 'openai/gpt-oss-20b', 'input_token',  0.075::numeric / 1000000),
            ('ai', 'groq', 'openai/gpt-oss-20b', 'output_token', 0.30::numeric / 1000000)
        ) AS entries(budget_kind, provider, operation, unit, unit_cost_usd)
    LOOP
        v_subject := concat_ws(':', v_entry.budget_kind, v_entry.provider, v_entry.operation, v_entry.unit);
        -- Also make direct SQL replay a no-op, including after an owner edit.
        IF EXISTS (SELECT 1 FROM public.entitlement_audit_log
                   WHERE action='provider_pricing_bootstrap' AND contract_ref=v_version
                     AND subject=v_subject) THEN
            CONTINUE;
        END IF;
        SELECT * INTO v_old FROM public.provider_cost_schedules
        WHERE budget_kind=v_entry.budget_kind AND provider=v_entry.provider
          AND operation=v_entry.operation AND unit=v_entry.unit FOR UPDATE;
        IF NOT FOUND THEN
            INSERT INTO public.provider_cost_schedules
                (budget_kind,provider,operation,unit,unit_cost_usd,source,verified_at,configured_by)
            VALUES (v_entry.budget_kind,v_entry.provider,v_entry.operation,v_entry.unit,
                    v_entry.unit_cost_usd,v_source,DATE '2026-10-28',v_version)
            RETURNING * INTO v_new;
            v_outcome := 'inserted';
        ELSIF v_old.unit_cost_usd IS NULL AND v_old.verified_at IS NULL
              AND v_old.configured_by='migration 20261028000000'
              AND v_old.source=v_placeholder AND v_old.safety_margin IS NULL
              AND v_old.charged_on_failure AND v_old.cost_is_final THEN
            -- Only the exact untouched historical bootstrap placeholder.
            UPDATE public.provider_cost_schedules
            SET unit_cost_usd=v_entry.unit_cost_usd,source=v_source,
                verified_at=DATE '2026-10-28',configured_by=v_version,updated_at=CURRENT_TIMESTAMP
            WHERE schedule_id=v_old.schedule_id RETURNING * INTO v_new;
            v_outcome := 'filled_placeholder';
        ELSE
            -- Includes configured prices (even zero), unverified owner rows,
            -- deliberate NULLs, different provenance, and earlier versions.
            v_new := v_old;
            v_outcome := 'preserved';
        END IF;
        INSERT INTO public.entitlement_audit_log
            (action,subject,old_value,new_value,contract_ref,approved_by,reason)
        VALUES ('provider_pricing_bootstrap',v_subject,
                CASE WHEN v_old.schedule_id IS NULL THEN NULL ELSE to_jsonb(v_old) END,
                jsonb_build_object('outcome',v_outcome,'schedule',to_jsonb(v_new),
                    'catalog_version',v_version,'approved_unit_cost_usd',v_entry.unit_cost_usd,
                    'source',v_source,'approved_on','2026-10-28',
                    'installed_by',session_user),
                v_version,'repository-approved catalog ' || v_version,
                'Owner-approved 2026-10-28: USD 0.075/million input and USD 0.30/million output; preserve configured schedules');
    END LOOP;
END
$catalog$;

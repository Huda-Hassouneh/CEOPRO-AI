CREATE TABLE "plan_price_versions" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "plan_id" UUID NOT NULL,
    "stripe_price_id" VARCHAR(255) NOT NULL,
    "period_code" VARCHAR(100) NOT NULL,
    "interval_unit" VARCHAR(10),
    "interval_count" INTEGER,
    "amount" DECIMAL(10,2),
    "currency" VARCHAR(3) NOT NULL,
    "retired_at" TIMESTAMPTZ(6),
    "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "plan_price_versions_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "plan_price_versions_plan_id_fkey" FOREIGN KEY ("plan_id") REFERENCES "plans"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "plan_price_versions_interval_count_check" CHECK ("interval_count" IS NULL OR "interval_count" > 0)
);

CREATE UNIQUE INDEX "plan_price_versions_stripe_price_id_key" ON "plan_price_versions"("stripe_price_id");
CREATE INDEX "plan_price_versions_plan_id_retired_at_idx" ON "plan_price_versions"("plan_id", "retired_at");

-- Preserve every currently published Price before any catalog edit can remove it.
INSERT INTO "plan_price_versions" ("plan_id", "stripe_price_id", "period_code", "interval_unit", "interval_count", "amount", "currency")
SELECT p."id", opt.value->>'stripePriceId', opt.value->>'period', NULL,
       NULL, NULL,
       p."currency"
FROM "plans" p
CROSS JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(p."billing_options"::jsonb) = 'array' THEN p."billing_options"::jsonb ELSE '[]'::jsonb END) opt(value)
WHERE NULLIF(opt.value->>'stripePriceId', '') IS NOT NULL
  AND NULLIF(opt.value->>'period', '') IS NOT NULL
ON CONFLICT ("stripe_price_id") DO NOTHING;

-- Older edits may have already removed a Price from billing_options. The
-- subscription still remembers its Stripe Price ID and period code.
INSERT INTO "plan_price_versions" ("plan_id", "stripe_price_id", "period_code", "interval_unit", "interval_count", "amount", "currency", "retired_at")
SELECT DISTINCT ON (s."payment_provider_price_id") s."plan_id", s."payment_provider_price_id",
       s."billing_period", NULL, NULL, NULL, p."currency", CURRENT_TIMESTAMP
FROM "subscriptions" s
JOIN "plans" p ON p."id" = s."plan_id"
WHERE NULLIF(s."payment_provider_price_id", '') IS NOT NULL
  AND NULLIF(s."billing_period", '') IS NOT NULL
ORDER BY s."payment_provider_price_id", s."created_at" DESC
ON CONFLICT ("stripe_price_id") DO NOTHING;

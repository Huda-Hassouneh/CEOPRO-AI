-- Pro plan terms (plan_key 'enterprise'): 500 products, 60 reports/month,
-- 50 team seats. Supersedes the 750 products / 60 seats set by
-- 20261020000000_keel_subscriptions_and_credits.sql. Reports stay at 60.
-- Standard, Plus and Custom are unchanged.
--
-- A new migration rather than an edit, so databases that already applied
-- 20261020000000 converge to the same values as fresh ones.
-- Undo: rollback/20261021000000_pro_plan_limits_500_products_50_seats.down.sql

UPDATE usage_plan_limits SET limit_value = 500 WHERE plan_key = 'enterprise' AND feature_code = 'tracked_products';
UPDATE usage_plan_limits SET limit_value = 50 WHERE plan_key = 'enterprise' AND feature_code = 'team_seats';

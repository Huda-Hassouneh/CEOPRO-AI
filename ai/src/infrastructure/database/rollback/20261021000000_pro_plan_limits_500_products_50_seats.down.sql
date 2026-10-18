-- Undoes migrations/20261021000000_pro_plan_limits_500_products_50_seats.sql:
-- restores Pro to 750 products and 60 seats (the 20261020000000 values).
UPDATE usage_plan_limits SET limit_value = 750 WHERE plan_key = 'enterprise' AND feature_code = 'tracked_products';
UPDATE usage_plan_limits SET limit_value = 60 WHERE plan_key = 'enterprise' AND feature_code = 'team_seats';

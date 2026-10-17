"""The Stripe catalog sync reconciles with what Stripe already holds, so a re-run
(or a run against a second database) never creates a duplicate price."""
import pytest

from src.ai.billing import catalog_sync as cs


def _row(i, plan, name, period, months, amount, stripe_price_id=None):
    return {"price_id": f"row{i}", "plan_key": plan, "display_name": name, "period_code": period,
            "interval_months": months, "amount": amount, "currency": "USD", "stripe_price_id": stripe_price_id}


def _price(pid, plan, period, months, cents, active=True, created=1):
    return {"id": pid, "active": active, "unit_amount": cents, "currency": "usd", "created": created,
            "recurring": {"interval": "month", "interval_count": months},
            "metadata": {"plan_key": plan, "period_code": period}}


ROWS = [_row(1, "starter", "Standard", "monthly", 1, 55.00), _row(2, "growth", "Plus", "monthly", 1, 140.00),
        _row(3, "enterprise", "Pro", "monthly", 1, 350.00)]
STRIPE = [_price("price_s", "starter", "monthly", 1, 5500), _price("price_g", "growth", "monthly", 1, 14000),
          _price("price_e", "enterprise", "monthly", 1, 35000)]


def kinds(actions):
    return [a.kind for a in actions]


def test_everything_already_in_stripe_is_adopted_and_nothing_is_created():
    actions = cs.plan(ROWS, STRIPE, "prod_1")
    assert kinds(actions) == ["adopt"] * 3 and [a.stripe_price_id for a in actions] == ["price_s", "price_g", "price_e"]
    created = []
    linked = {}
    done = cs.apply(actions, lambda r, p: linked.update({r: p}), lambda params: created.append(params) or {"id": "x"})
    assert done == {"adopted": 3, "created": 0} and created == [] and linked == {"row1": "price_s", "row2": "price_g", "row3": "price_e"}


def test_a_second_run_changes_nothing():
    rows = [dict(r, stripe_price_id=p["id"]) for r, p in zip(ROWS, STRIPE)]
    actions = cs.plan(rows, STRIPE, "prod_1")
    assert kinds(actions) == ["verify_ok"] * 3
    assert cs.apply(actions, lambda *a: pytest.fail("linked"), lambda p: pytest.fail("created")) == {"adopted": 0, "created": 0}


def test_only_the_missing_price_is_created():
    actions = cs.plan(ROWS, STRIPE[:2], "prod_1")
    assert kinds(actions) == ["adopt", "adopt", "create"]
    create = actions[2].params
    assert create["unit_amount"] == 35000 and create["currency"] == "usd" and create["product"] == "prod_1"
    assert create["recurring"] == {"interval": "month", "interval_count": 1}
    assert create["metadata"] == {"plan_key": "enterprise", "period_code": "monthly"}


def test_duplicate_prices_adopt_the_oldest_and_create_nothing():
    twin = _price("price_s2", "starter", "monthly", 1, 5500, created=5)
    actions = cs.plan(ROWS[:1], [twin, _price("price_s", "starter", "monthly", 1, 5500, created=1)], "prod_1")
    assert kinds(actions) == ["adopt", "duplicate"]
    assert actions[0].stripe_price_id == "price_s" and actions[1].stripe_price_id == "price_s2"


def test_a_changed_amount_creates_a_new_price_and_flags_the_old_one():
    actions = cs.plan([_row(1, "starter", "Standard", "monthly", 1, 60.00)], [STRIPE[0]], "prod_1")
    assert kinds(actions) == ["superseded", "create"] and actions[0].stripe_price_id == "price_s"
    assert actions[1].params["unit_amount"] == 6000


def test_an_active_price_with_the_wrong_interval_is_not_adopted():
    wrong = _price("price_x", "starter", "monthly", 3, 5500)
    assert kinds(cs.plan(ROWS[:1], [wrong], "prod_1")) == ["superseded", "create"]


def test_two_rows_never_claim_the_same_stripe_price():
    rows = [_row(1, "starter", "Standard", "monthly", 1, 55.00), _row(2, "starter", "Standard", "monthly", 1, 55.00)]
    assert kinds(cs.plan(rows, [STRIPE[0]], "prod_1")) == ["adopt", "create"]


def test_database_drift_and_missing_prices_are_reported_not_overwritten():
    drifted = dict(ROWS[0], stripe_price_id="price_s", amount=99.00)
    gone = dict(ROWS[1], stripe_price_id="price_gone")
    actions = cs.plan([drifted, gone], STRIPE, "prod_1")
    assert kinds(actions) == ["drift", "missing"] and len(cs.problems(actions)) == 2


def test_product_selection():
    ours = {"id": "prod_a", "name": "KEEL", "metadata": {"app": "apex"}}
    assert cs.pick_product([ours, {"id": "prod_o", "name": "Other", "metadata": {}}], None) == "prod_a"
    assert cs.pick_product([], None) is None
    assert cs.pick_product([ours], "prod_a") == "prod_a"
    with pytest.raises(cs.CatalogError):
        cs.pick_product([ours, dict(ours, id="prod_b")], None)       # ambiguous: refuse to guess
    with pytest.raises(cs.CatalogError):
        cs.pick_product([ours], "prod_missing")                      # configured id not in Stripe


def test_minor_units():
    assert cs.minor_units(55.0, "USD") == 5500 and cs.minor_units(1680, "jpy") == 1680

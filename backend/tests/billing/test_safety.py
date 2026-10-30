import pytest
from scripts.billing_verification import VerificationRefused, validate_test_environment


@pytest.mark.parametrize("key", ["sk_live_not_real", "rk_live_not_real", "arbitrary"])
def test_live_or_unknown_stripe_keys_are_refused(key):
    with pytest.raises(VerificationRefused):
        validate_test_environment({"STRIPE_SECRET_KEY": key})


@pytest.mark.parametrize("key", ["", "sk_test_offline", "rk_test_offline"])
def test_offline_or_test_keys_are_accepted(key):
    assert validate_test_environment({"STRIPE_SECRET_KEY": key}) is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://owner:secret@127.0.0.1:5433/KEEL_DEV",
        "postgresql://owner:secret@remote.example:5432/keel_billing_test",
        "postgresql://owner:secret@127.0.0.1/keel_billing_test",
        "postgresql://owner:secret@127.0.0.1:5433/production_test",
        "postgresql://owner:secret@127.0.0.1:5433/keel_billing_test?options=x",
        "postgresql://owner:secret@127.0.0.1:bad/keel_billing_test",
        "",
    ],
)
def test_unsafe_databases_are_refused_without_exposing_the_url(url):
    with pytest.raises(VerificationRefused) as error:
        validate_test_environment({"BILLING_TEST_DATABASE_URL": url}, database=True)
    assert "secret" not in str(error.value)


def test_database_url_is_explicit_and_not_taken_from_application_environment():
    with pytest.raises(VerificationRefused):
        validate_test_environment(
            {"DATABASE_URL": "postgresql://owner@localhost:5432/keel_billing_test"},
            database=True,
        )


def test_explicit_local_disposable_database_is_accepted():
    url = "postgresql://owner:secret@127.0.0.1:55439/keel_billing_test"
    assert (
        validate_test_environment({"BILLING_TEST_DATABASE_URL": url}, database=True)
        == url
    )


@pytest.mark.parametrize(
    "name",
    ["KEEL_INTEGRATION_TEST", "KEEL_INTEGRATION_TEST_UPGRADE"],
)
def test_explicit_keel_integration_database_names_are_accepted(name):
    url = f"postgresql://tester@127.0.0.1:55439/{name}"
    assert (
        validate_test_environment({"BILLING_TEST_DATABASE_URL": url}, database=True)
        == url
    )


@pytest.mark.parametrize("name", ["KEEL_DEV", "keel_integration_test"])
def test_non_test_database_names_are_refused(name):
    url = f"postgresql://tester@127.0.0.1:55439/{name}"
    with pytest.raises(VerificationRefused):
        validate_test_environment({"BILLING_TEST_DATABASE_URL": url}, database=True)


@pytest.mark.parametrize("apply", [False, True])
def test_catalog_delegates_to_existing_main_sync_in_test_mode(monkeypatch, apply):
    from types import SimpleNamespace

    from scripts import billing_verification

    url = "postgresql://owner:secret@127.0.0.1:55439/keel_billing_test"
    monkeypatch.setenv("BILLING_TEST_DATABASE_URL", url)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_offline")
    monkeypatch.setenv("CONFIRM_LIVE_STRIPE", "YES")
    calls = []
    monkeypatch.setattr(
        billing_verification.subprocess,
        "run",
        lambda command, **kw: (
            calls.append((command, kw)) or SimpleNamespace(returncode=0)
        ),
    )
    assert (
        billing_verification.main(["catalog-test"] + (["--apply"] if apply else []))
        == 0
    )
    command, options = calls[0]
    assert command[1:4] == ["-m", "scripts.stripe_sync_catalog"] + (
        [] if apply else ["--dry-run"]
    )
    assert options["env"]["DATABASE_URL"] == url
    assert "CONFIRM_LIVE_STRIPE" not in options["env"]


def test_catalog_without_credentials_does_not_start_a_subprocess(monkeypatch):
    from scripts import billing_verification

    monkeypatch.setenv(
        "BILLING_TEST_DATABASE_URL",
        "postgresql://owner@localhost:55439/keel_billing_test",
    )
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    monkeypatch.setattr(
        billing_verification.subprocess,
        "run",
        lambda *a, **kw: pytest.fail("Missing credentials reached Stripe"),
    )
    assert billing_verification.main(["catalog-test"]) == 2

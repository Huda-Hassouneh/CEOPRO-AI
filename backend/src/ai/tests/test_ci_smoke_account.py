from types import SimpleNamespace

import pytest

from scripts.ci_smoke_account import _verify_synthetic_account
from scripts.demo_companies.seed import Client, sign_in


def test_seed_client_errors_never_include_authentication_response_body(monkeypatch):
    client = Client("http://127.0.0.1:8000")
    body = "registration_token=synthetic-token password=synthetic-password eyJhbGciOiJIUzI1NiJ9.payload.signature"
    monkeypatch.setattr(client.http, "request", lambda *args, **kwargs: SimpleNamespace(status_code=500, text=body))

    with pytest.raises(RuntimeError) as error:
        client.request("POST", "/auth/email/verify?token=synthetic-token")

    message = str(error.value)
    assert "HTTP 500" in message
    assert "registration_token" not in message
    assert "synthetic-token" not in message
    assert "synthetic-password" not in message
    assert "eyJhbGciOiJIUzI1NiJ9" not in message
    assert "/auth/email/verify" not in message


def test_general_seed_helper_reports_pending_verification_without_exposing_response(monkeypatch):
    client = Client("https://api.example.test")
    responses = iter([
        SimpleNamespace(status_code=401, json=lambda: {}),
        SimpleNamespace(status_code=202, json=lambda: {
            "status": "pending_verification",
            "registration_token": "synthetic-registration-token",
            "email_verification_code": "synthetic-code",
        }),
    ])
    monkeypatch.setattr(client.http, "post", lambda *args, **kwargs: next(responses))
    company = SimpleNamespace(owner_name="CI Owner", business_name="CI Company", country="JO", currency="JOD")

    with pytest.raises(RuntimeError, match="pending email verification") as error:
        sign_in(client, company, "ci@keel-ci.example", "synthetic-password")

    assert "synthetic-registration-token" not in str(error.value)
    assert "synthetic-code" not in str(error.value)
    assert "synthetic-password" not in str(error.value)


@pytest.mark.parametrize("api", ["https://api.example.com", "http://192.0.2.10:8000"])
def test_synthetic_verification_fixture_refuses_non_loopback_api(api):
    client = Client(api)

    with pytest.raises(RuntimeError, match="loopback HTTP API"):
        _verify_synthetic_account(client, None, "ci@keel-ci.example", "synthetic-only")

    client.http.close()


from scripts.ci_smoke_account import _complete_guided_onboarding


class GuidedClient:
    def __init__(self, highest=0, complete=False, access=True):
        self.state = {"highestCompletedStep": highest, "revision": highest, "isComplete": complete}
        self.access = access
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        if path == "/onboarding/state" and method == "GET":
            return self.state.copy()
        if path == "/billing/subscription":
            return {"assigned": self.access, "hasAccess": self.access, "planId": "growth", "billingPeriod": "monthly"}
        if method == "PUT":
            body = kwargs["json"]
            assert body["expected_revision"] == self.state["revision"]
            assert body["step"] == self.state["highestCompletedStep"] + 1
            self.state.update(highestCompletedStep=body["step"], revision=self.state["revision"] + 1)
            return self.state.copy()
        assert method == "POST" and path == "/settings/company/onboarding/complete"
        assert self.state["highestCompletedStep"] == 5
        return {"onboarding_completed_at": "2026-10-27T00:00:00Z"}


@pytest.mark.parametrize("highest", [0, 1, 4, 5])
def test_smoke_saves_missing_steps_then_acknowledges_actual_trial(highest):
    client = GuidedClient(highest=highest)
    company = SimpleNamespace(country="JO", city="Amman", language="en")
    _complete_guided_onboarding(client, company)
    writes = [kwargs["json"] for method, _, kwargs in client.calls if method == "PUT"]
    assert [item["step"] for item in writes] == list(range(highest + 1, 6))
    if writes:
        assert writes[-1]["selectedPlan"] == "growth"
        assert writes[-1]["billingPeriod"] == "monthly"
    assert client.calls[-1][1] == "/settings/company/onboarding/complete"
    assert not any("checkout" in path or path == "/billing/trial" for _, path, _ in client.calls)


def test_completed_smoke_account_is_read_only_on_repeat():
    client = GuidedClient(highest=5, complete=True)
    _complete_guided_onboarding(client, None)
    assert all(method == "GET" for method, _, _ in client.calls)


def test_smoke_refuses_expired_or_unassigned_rights_instead_of_creating_payment():
    client = GuidedClient(access=False)
    with pytest.raises(RuntimeError, match="valid signup trial"):
        _complete_guided_onboarding(client, None)
    assert all(method == "GET" for method, _, _ in client.calls)

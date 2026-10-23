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

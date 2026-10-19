"""scripts/llm_provider_check.py: reports a missing model price (the
COST_NOT_CONFIGURED blocker), checks the provider serves the model without a
billed call, and makes its one real request only inside metering()."""
from decimal import Decimal

import httpx

from scripts import llm_provider_check as check
from src.ai.billing import credits
from src.ai.rag import llm_client

MODEL = "openai/gpt-oss-20b"


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code, self._payload, self.text = status_code, payload or {}, ""

    def json(self):
        return self._payload


def _setup(monkeypatch, *, served=(MODEL,), prices=None):
    monkeypatch.setattr(llm_client, "active_provider", lambda: "groq")
    monkeypatch.setattr(llm_client, "provider_configured", lambda: True)
    monkeypatch.setattr(llm_client, "MODEL_NAME", MODEL)
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key-value")
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    class _Conn:
        def close(self):
            pass

    from src.ai import db

    monkeypatch.setattr(db, "system_connection", lambda: _Conn())
    monkeypatch.setattr(credits, "schedule", lambda conn, kind, provider, operation: prices or {})
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return _Response(200, {"data": [{"id": model} for model in served]})

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


PRICED = {"input_token": {"cost": Decimal("0.000000075")}, "output_token": {"cost": Decimal("0.0000003")}}


def test_a_model_without_a_confirmed_price_fails_and_says_how_to_fix_it(monkeypatch, capsys):
    _setup(monkeypatch, prices={})
    assert check.main([]) == 1
    out = capsys.readouterr().out
    assert "COST_NOT_CONFIGURED" in out and "billing_admin.py" in out
    assert "test-groq-key-value" not in out


def test_priced_and_served_passes_without_any_billed_call(monkeypatch, capsys):
    calls = _setup(monkeypatch, prices=PRICED)
    monkeypatch.setattr(llm_client, "chat_completion", lambda *a, **k: (_ for _ in ()).throw(AssertionError("billed")))
    assert check.main([]) == 0
    out = capsys.readouterr().out
    assert "$0.075 input / $0.3 output per 1M tokens" in out
    assert calls == [check.MODEL_LISTS["groq"]]


def test_a_model_the_provider_does_not_serve_fails(monkeypatch, capsys):
    _setup(monkeypatch, served=("some/other-model",), prices=PRICED)
    assert check.main([]) == 1
    assert "doesn't serve openai/gpt-oss-20b" in capsys.readouterr().out


def test_the_real_request_runs_inside_metering_for_the_named_company(monkeypatch, capsys):
    _setup(monkeypatch, prices=PRICED)
    seen = []

    def fake_completion(messages, max_tokens):
        seen.append(credits.current())
        return "ready"

    monkeypatch.setattr(llm_client, "chat_completion", fake_completion)
    assert check.main(["--tenant", "11111111-1111-1111-1111-111111111111"]) == 0
    assert seen and seen[0].tenant_id == "11111111-1111-1111-1111-111111111111"
    assert seen[0].operation_type == "llm_provider_check"
    assert "metered for tenant" in capsys.readouterr().out


def test_a_refused_real_request_reports_the_billing_reason(monkeypatch, capsys):
    _setup(monkeypatch, prices=PRICED)

    def refused(messages, max_tokens):
        raise credits.BudgetError("BUDGET_EXHAUSTED", credits.AI)

    monkeypatch.setattr(llm_client, "chat_completion", refused)
    assert check.main(["--tenant", "11111111-1111-1111-1111-111111111111"]) == 1
    assert "BUDGET_EXHAUSTED" in capsys.readouterr().out

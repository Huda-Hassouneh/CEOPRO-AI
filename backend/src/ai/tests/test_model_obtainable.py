"""The model availability probe: honest offline, and a failure is remembered."""
from src.ai.core import ml_runtime


def test_offline_without_cached_weights_is_unavailable(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert ml_runtime.model_obtainable("org/definitely-not-cached-model") is False


def test_a_local_directory_is_always_available(tmp_path):
    assert ml_runtime.model_obtainable(str(tmp_path)) is True


def test_an_unavailable_model_is_not_probed_again_for_a_while(monkeypatch):
    calls = []
    monkeypatch.setattr(ml_runtime, "_model_obtainable", lambda name, timeout=3.0: calls.append(name) or False)
    assert ml_runtime.model_obtainable("org/blocked") is False
    assert ml_runtime.model_obtainable("org/blocked") is False
    assert calls == ["org/blocked"]

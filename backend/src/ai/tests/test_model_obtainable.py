"""The model availability probe: honest offline, and a failure is remembered."""
from src.ai.core import ml_runtime


def test_offline_without_cached_weights_is_unavailable(monkeypatch):
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert ml_runtime.model_obtainable("org/definitely-not-cached-model") is False


def test_a_local_directory_is_always_available(tmp_path):
    assert ml_runtime.model_obtainable(str(tmp_path)) is True


def test_an_unavailable_model_is_not_probed_again_for_a_while(monkeypatch):
    calls = []
    monkeypatch.setattr(ml_runtime, "_model_obtainable", lambda name, timeout=3.0, weights=(): calls.append(name) or False)
    assert ml_runtime.model_obtainable("org/blocked") is False
    assert ml_runtime.model_obtainable("org/blocked") is False
    assert calls == ["org/blocked"]


def test_availability_is_judged_by_the_files_the_caller_will_load(monkeypatch):
    """An ONNX export can be reachable while the torch weights aren't, and the
    other way round - each set of files is probed and remembered on its own."""
    calls = []
    monkeypatch.setattr(ml_runtime, "_model_obtainable",
                        lambda name, timeout=3.0, weights=(): calls.append(weights) or weights == ("onnx/model.onnx",))
    assert ml_runtime.model_obtainable("org/m") is False
    assert ml_runtime.model_obtainable("org/m", weights=("onnx/model.onnx",)) is True
    assert calls == [ml_runtime.WEIGHT_FILES, ("onnx/model.onnx",)]


def test_a_refused_token_is_logged_as_such_not_as_an_unreachable_host(monkeypatch, caplog):
    import urllib.error
    import urllib.request

    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    caplog.set_level("ERROR", logger="KEEL_ML_RUNTIME")
    assert ml_runtime._model_obtainable("org/uncached-model-for-token-test") is False
    assert "invalid or expired" in caplog.text and "401" in caplog.text

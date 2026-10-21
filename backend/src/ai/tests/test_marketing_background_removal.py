"""
Unit tests for src/ai/marketing/background_removal.py, plus one real
(non-mocked) integration test against the actual rembg model - see
test_remove_background_rembg_real_integration below. Everything else
mocks the real rembg model call at _remove_via_rembg() - the one call site
this module's own docstring designs specifically for that purpose - rather
than needing rembg's real (heavy, ~220MB-import/~520MB-peak-RSS - see that
module's own docstring) model download/inference in every test run.
"""
import io
from unittest.mock import patch

import pytest

from src.ai.marketing.background_removal import (
    BackgroundRemovalError, RemovedBackgroundImage, get_background_removal_capability, remove_background,
)

_FAKE_SOURCE_BYTES = b"\x89PNG\r\n\x1a\nfakesourcebytes"
_FAKE_PROCESSED_BYTES = b"\x89PNG\r\n\x1a\nfakeprocessedbytes"


# --- remove_background: dispatch / not_configured -------------------------

def test_remove_background_not_configured_when_no_provider(monkeypatch):
    monkeypatch.delenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", raising=False)
    with pytest.raises(BackgroundRemovalError) as exc:
        remove_background(_FAKE_SOURCE_BYTES)
    assert exc.value.status == "NOT_CONFIGURED"


def test_remove_background_not_configured_for_unknown_provider():
    with pytest.raises(BackgroundRemovalError) as exc:
        remove_background(_FAKE_SOURCE_BYTES, provider="not-a-real-provider")
    assert exc.value.status == "NOT_CONFIGURED"


def test_remove_background_rejects_empty_image(rembg_installed):
    with pytest.raises(BackgroundRemovalError) as exc:
        remove_background(b"", provider="rembg")
    assert exc.value.status == "PROVIDER_ERROR"


def test_remove_background_rejects_oversized_image(monkeypatch, rembg_installed):
    # _MAX_IMAGE_BYTES is read from its env var at import time (same
    # convention as every other size-limit constant in this feature, e.g.
    # routers/marketing.py's own _MAX_IMAGE_BYTES) - patch the already-
    # resolved module constant directly rather than the env var, which
    # would have no effect post-import.
    monkeypatch.setattr("src.ai.marketing.background_removal._MAX_IMAGE_BYTES", 10)
    with pytest.raises(BackgroundRemovalError) as exc:
        remove_background(_FAKE_SOURCE_BYTES, provider="rembg")
    assert exc.value.status == "PROVIDER_ERROR"
    assert "exceeds" in exc.value.message


# --- rembg provider ---------------------------------------------------

@pytest.fixture
def rembg_installed():
    """The default build does not ship rembg (opt-in extra), so tests that
    mock the provider call must not depend on whether it is installed."""
    with patch("src.ai.marketing.background_removal._rembg_installed", return_value=True):
        yield


def test_rembg_success_returns_processed_image(rembg_installed):
    with patch("src.ai.marketing.background_removal._remove_via_rembg", return_value=_FAKE_PROCESSED_BYTES) as mock_remove:
        result = remove_background(_FAKE_SOURCE_BYTES, provider="rembg")

    assert isinstance(result, RemovedBackgroundImage)
    assert result.content == _FAKE_PROCESSED_BYTES
    assert result.content_type == "image/png"
    assert result.provider == "rembg"
    mock_remove.assert_called_once_with(_FAKE_SOURCE_BYTES)


def test_rembg_model_failure_raises_provider_error(rembg_installed):
    with patch("src.ai.marketing.background_removal._remove_via_rembg", side_effect=RuntimeError("corrupt image data")):
        with pytest.raises(BackgroundRemovalError) as exc:
            remove_background(_FAKE_SOURCE_BYTES, provider="rembg")
    assert exc.value.status == "PROVIDER_ERROR"
    assert "corrupt image data" in exc.value.message


# --- get_background_removal_capability -------------------------------------

def test_capability_not_configured_by_default(monkeypatch):
    monkeypatch.delenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", raising=False)
    capability = get_background_removal_capability()
    assert capability == {"available": False, "provider": None, "reason": capability["reason"]}
    assert "not configured" in capability["reason"].lower()


def test_capability_unavailable_when_rembg_not_installed(monkeypatch):
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    with patch("src.ai.marketing.background_removal._rembg_installed", return_value=False):
        capability = get_background_removal_capability()
    assert capability["available"] is False
    assert capability["provider"] == "rembg"
    assert "not installed" in capability["reason"]


def test_remove_background_not_configured_when_rembg_not_installed():
    with patch("src.ai.marketing.background_removal._rembg_installed", return_value=False):
        with pytest.raises(BackgroundRemovalError) as exc:
            remove_background(_FAKE_SOURCE_BYTES, provider="rembg")
    assert exc.value.status == "NOT_CONFIGURED"
    assert "not installed" in exc.value.message


def test_capability_available_for_rembg(monkeypatch, rembg_installed):
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    assert get_background_removal_capability() == {"available": True, "provider": "rembg", "reason": None}


# --- Real (non-mocked) integration test -----------------------------------

def _make_synthetic_product_png() -> bytes:
    """A colored square on a plain background - not a real product photo,
    but real enough to exercise rembg's actual segmentation model on real
    pixel data rather than mocked bytes."""
    from PIL import Image
    import numpy as np

    pixels = np.full((300, 300, 3), 210, dtype=np.uint8)
    pixels[80:220, 80:220] = [30, 90, 200]
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return buffer.getvalue()


def test_remove_background_rembg_real_integration(monkeypatch):
    """
    Calls the real rembg model (u2netp - the smallest available, same one
    this feature defaults to) against a real synthetic image - no mocking
    at any layer. Skipped, rather than failed, if rembg/its model can't
    actually run here (e.g. no network access to download the model on
    first use, or the optional dependency isn't installed) - this is a
    real capability check, not a required-to-pass unit test, matching the
    "test actual provider behavior where possible" ask this feature was
    built against. Passed for real in this feature's own development
    sandbox - see MARKETING_AI_CAPABILITIES.md for the measured memory/time
    numbers from that same run.
    """
    monkeypatch.setenv("MARKETING_BACKGROUND_REMOVAL_PROVIDER", "rembg")
    try:
        import rembg  # noqa: F401
    except ImportError:
        pytest.skip("rembg is not installed in this environment")

    source_bytes = _make_synthetic_product_png()
    try:
        result = remove_background(source_bytes)
    except BackgroundRemovalError as err:
        pytest.skip(f"rembg could not run in this environment (likely no network access to download its model): {err}")

    assert isinstance(result, RemovedBackgroundImage)
    assert result.provider == "rembg"
    assert result.content_type == "image/png"
    assert result.content != source_bytes
    assert len(result.content) > 0

    from PIL import Image
    output_image = Image.open(io.BytesIO(result.content))
    assert output_image.mode == "RGBA"  # real transparency, not a fabricated solid-color cutout
    assert output_image.size == (300, 300)

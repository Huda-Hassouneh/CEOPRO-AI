"""P1 (QA_TEST_STRATEGY.md): internal service-to-service token verification."""
import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET", "unit-test-static-secret")

with patch("redis.Redis"):
    from src.infrastructure import security  # noqa: E402


def _verify(token):
    return asyncio.run(security.verify_internal_service_token(MagicMock(), token))


def test_missing_token_is_403():
    with pytest.raises(HTTPException) as exc:
        _verify(None)
    assert exc.value.status_code == 403


def test_empty_token_is_403():
    with pytest.raises(HTTPException) as exc:
        _verify("")
    assert exc.value.status_code == 403


def test_rotated_token_is_accepted():
    with patch.object(security._rotation_engine, "validate_incoming_token", return_value=True):
        assert _verify("rotated") == "rotated"


def test_static_fallback_is_accepted_when_rotation_rejects():
    with patch.object(security._rotation_engine, "validate_incoming_token", return_value=False):
        assert _verify(security._STATIC_FALLBACK) == security._STATIC_FALLBACK


def test_static_fallback_still_works_when_redis_is_down():
    with patch.object(security._rotation_engine, "validate_incoming_token", side_effect=ConnectionError("redis down")):
        assert _verify(security._STATIC_FALLBACK) == security._STATIC_FALLBACK


def test_wrong_token_is_403_even_when_redis_is_down():
    with patch.object(security._rotation_engine, "validate_incoming_token", side_effect=ConnectionError("redis down")):
        with pytest.raises(HTTPException) as exc:
            _verify("wrong")
    assert exc.value.status_code == 403


def test_403_detail_does_not_echo_the_secret():
    with patch.object(security._rotation_engine, "validate_incoming_token", return_value=False):
        with pytest.raises(HTTPException) as exc:
            _verify("wrong")
    assert security._STATIC_FALLBACK not in exc.value.detail

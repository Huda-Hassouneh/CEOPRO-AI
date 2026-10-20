"""Real isolated Redis check, gated independently from PostgreSQL and never flushed."""
import os
import uuid
from urllib.parse import urlsplit
import pytest
from fastapi import HTTPException
from src.ai.core import security

pytestmark=pytest.mark.skipif(not os.getenv('PHASE1A_REDIS_TEST_URL') or os.getenv('BILLING_DATABASE_TESTS')!='1',reason='BLOCKED: isolated Redis URL not supplied')


def test_real_revocation_persists_with_ttl_and_outage_is_not_permission(monkeypatch):
    import redis
    url=os.environ['PHASE1A_REDIS_TEST_URL'];parts=urlsplit(url)
    assert os.getenv('PHASE1A_ISOLATED_REDIS')=='YES'and parts.hostname in {'127.0.0.1','localhost','::1'}and parts.port
    assert parts.scheme=='redis'and not parts.query and not parts.fragment
    client=redis.Redis.from_url(url,socket_connect_timeout=1,socket_timeout=1)
    key='phase1a-test:'+uuid.uuid4().hex
    token_id=uuid.uuid4().hex
    monkeypatch.setattr(security,'_REVOKED_PREFIX',key+':');monkeypatch.setattr(security,'_revocation_store',lambda:client)
    try:
        assert security.is_token_revoked(token_id)is False
        assert security.revoke_token(token_id,None)is True
        assert security.is_token_revoked(token_id)is True
        assert client.ttl(key+':'+token_id)>0
        client.delete(key+':'+token_id)
        assert security.is_token_revoked(token_id)is True  # Durable receipt survives a cache reset.
        def unavailable():raise ConnectionError('isolated outage boundary')
        monkeypatch.setattr(security,'_revocation_store',unavailable)
        with pytest.raises(HTTPException)as error:security.is_token_revoked(token_id)
        assert error.value.status_code==503
    finally:client.delete(key+':'+token_id);client.close()

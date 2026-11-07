"""What the API and the processor agree on: canonical task bodies, the
job id derived from them, and the request signature.

Every request carries ``X-Offload-Timestamp`` and ``X-Offload-Signature`` =
HMAC-SHA256(secret, "<timestamp>.<method>.<path>.<body>"). The processor
refuses anything unsigned, signed with another secret, or older than
``MAX_SKEW_SECONDS`` (a captured request cannot be replayed later).
"""
import hashlib
import hmac
import json
import time
from typing import Any, Optional

PROTOCOL_VERSION = 1
MAX_SKEW_SECONDS = 300
TIMESTAMP_HEADER = "X-Offload-Timestamp"
SIGNATURE_HEADER = "X-Offload-Signature"
MIN_SECRET_LENGTH = 32


def canonical(value: Any) -> bytes:
    """The same task always serialises to the same bytes (sorted keys, no spaces)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=list).encode()


def job_key(kind: str, params: dict) -> str:
    """Stable id of a task: identical work gets the same id, so it runs once."""
    digest = hashlib.sha256(canonical({"v": PROTOCOL_VERSION, "kind": kind, "params": params})).hexdigest()
    return digest[:40]


def _message(timestamp: str, method: str, path: str, body: bytes) -> bytes:
    return b".".join([timestamp.encode(), method.upper().encode(), path.encode(), body or b""])


def sign(secret: str, method: str, path: str, body: bytes = b"", now: Optional[float] = None) -> dict:
    timestamp = str(int(now if now is not None else time.time()))
    signature = hmac.new(secret.encode(), _message(timestamp, method, path, body), hashlib.sha256).hexdigest()
    return {TIMESTAMP_HEADER: timestamp, SIGNATURE_HEADER: signature}


def verify(secret: str, method: str, path: str, body: bytes, timestamp: Optional[str], signature: Optional[str],
           now: Optional[float] = None) -> bool:
    if not secret or not timestamp or not signature or not timestamp.isdigit():
        return False
    current = now if now is not None else time.time()
    if abs(current - int(timestamp)) > MAX_SKEW_SECONDS:
        return False
    expected = hmac.new(secret.encode(), _message(timestamp, method, path, body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

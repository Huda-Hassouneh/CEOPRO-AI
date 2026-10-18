"""
KEEL - Field-level encryption for data_sources.connection_credentials_vault.

Closes PENDING_ACTIONS.md #42: that column was a plain TEXT field holding
raw JSON credentials - functionally correct and RLS-scoped like any other
column, but no field-level encryption, no external vault/KMS reference.
A stolen database dump alone was enough to read every stored credential.

Honest framing, not oversold: this is real **envelope encryption at
rest**, not literal "zero-knowledge" - a collector that actually calls a
vendor's API needs the real plaintext credential in memory at the moment
of that call, there is no way around that for a system that itself makes
the API call. What this DOES guarantee, and is the actual, meaningful
security property: a stolen database dump ALONE is now useless. Every
credential is encrypted with its own random, per-write Data Encryption
Key (DEK); the DEK itself is never stored in the clear - it's "wrapped"
(encrypted) by a Key Encryption Key a KMS backend holds, and that KMS
backend is never the database. Decrypting a credential requires BOTH the
database row AND a live, authorized call to the KMS backend - exactly
the property "if our system gets hacked, client data must remain
encrypted" is actually asking for.

Two backends behind one interface, so switching is a config change, not a
code change (same pattern this codebase already uses for the social
collector vendor switch - see market_scraper/README.md's "Vendor
policy"):

- **LocalEnvelopeKMS** - a real, working default requiring no cloud
  account, good for self-hosted/dev deployments and this module's own
  tests. The "master key" wrapping every DEK is a single Fernet key from
  CREDENTIAL_VAULT_MASTER_KEY - genuinely weaker than a real KMS (the key
  lives in an env var, not a hardware-backed service), flagged plainly as
  the honest trade-off, not hidden.
- **AWSKMSBackend** - the real production answer: every DEK is wrapped by
  an actual AWS KMS key (hardware-backed, access-logged, revocable
  independently of the database). boto3 is imported lazily (only when
  this backend is actually instantiated) so a deployment using only the
  local backend never needs the dependency installed.

HashiCorp Vault is a real, documented alternative KMS backend behind this
same interface - not built in this pass (this codebase's own convention,
PENDING_ACTIONS.md, is to flag a real infra/vendor decision rather than
pick unilaterally); implementing it means adding one more class that
implements wrap_dek()/unwrap_dek(), nothing else in this module changes.
"""
import base64
import json
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_ENVELOPE_VERSION = 1

GENERATE_COMMAND = 'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'


def master_key_problem(value: Optional[str]) -> Optional[str]:
    """Why a CREDENTIAL_VAULT_MASTER_KEY value can't be used, or None when it
    is a valid Fernet key (32 bytes, URL-safe base64, 44 characters). Never
    includes the value itself."""
    if not value or not value.strip():
        return "is not set"
    value = value.strip()
    if value.lower().startswith("change_this"):
        return "is still the placeholder from .env.example"
    if len(value) == 64 and all(c in "0123456789abcdefABCDEF" for c in value):
        return ("is a 64-character hex string (e.g. from `openssl rand -hex 32`), not a Fernet key - "
                f"generate one with: {GENERATE_COMMAND}")
    try:
        Fernet(value.encode())
    except (ValueError, TypeError):
        return f"is not a valid Fernet key (expected 44 URL-safe base64 characters) - generate one with: {GENERATE_COMMAND}"
    return None


def previous_master_keys() -> list:
    """CREDENTIAL_VAULT_PREVIOUS_KEYS: comma-separated keys that were the
    master key before a rotation. Kept only until scripts/vault_key.py
    rewrap has re-wrapped every stored credential under the current key."""
    return [k.strip() for k in (os.getenv("CREDENTIAL_VAULT_PREVIOUS_KEYS") or "").split(",") if k.strip()]


class CredentialDecryptionError(ValueError):
    """Raised when a stored envelope can't be decrypted - a real,
    actionable failure (wrong KMS backend configured, wrong master key,
    an unauthorized/expired KMS credential) that must never be silently
    swallowed into an empty {} the way a malformed legacy blob used to be."""


class KMSBackend:
    """Wraps/unwraps a Data Encryption Key (DEK) - never touches the
    credential plaintext itself, only the (much smaller) DEK that
    encrypts it. `name` is stored in every envelope so a later read knows
    which backend must be used to decrypt it - decrypting with the wrong
    backend fails loud (CredentialDecryptionError), never silently."""

    name = "unknown"

    def wrap_dek(self, plaintext_dek: bytes) -> bytes:
        raise NotImplementedError

    def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        raise NotImplementedError


class LocalEnvelopeKMS(KMSBackend):
    name = "local"

    def __init__(self, master_key: Optional[str] = None, previous_keys: Optional[list] = None):
        """New credentials are always wrapped with the current master key;
        reading also tries the previous keys (CREDENTIAL_VAULT_PREVIOUS_KEYS),
        so rotating the master key never makes stored credentials unreadable.
        An invalid key refuses to start the backend - it is never derived,
        padded or replaced, which would silently make existing credentials
        unreadable."""
        key = master_key if master_key is not None else os.getenv("CREDENTIAL_VAULT_MASTER_KEY")
        problem = master_key_problem(key.decode() if isinstance(key, bytes) else key)
        if problem:
            raise RuntimeError(f"CREDENTIAL_VAULT_MASTER_KEY {problem}")
        previous = previous_master_keys() if previous_keys is None else list(previous_keys)
        for index, old in enumerate(previous, 1):
            old_problem = master_key_problem(old)
            if old_problem:
                raise RuntimeError(f"CREDENTIAL_VAULT_PREVIOUS_KEYS entry {index} {old_problem}")
        self._current = Fernet(key.strip().encode() if isinstance(key, str) else key)
        self._fernet = MultiFernet([self._current] + [Fernet(k.encode()) for k in previous])
        self.previous_key_count = len(previous)

    def wrap_dek(self, plaintext_dek: bytes) -> bytes:
        return self._current.encrypt(plaintext_dek)

    def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        try:
            return self._fernet.decrypt(wrapped_dek)
        except InvalidToken as e:
            raise CredentialDecryptionError(
                "local KMS backend could not unwrap this DEK with the current or any previous master key - "
                "the key it was stored under is not configured (CREDENTIAL_VAULT_PREVIOUS_KEYS)") from e

    def wrapped_with_current_key(self, wrapped_dek: bytes) -> bool:
        try:
            self._current.decrypt(wrapped_dek)
            return True
        except InvalidToken:
            return False


class AWSKMSBackend(KMSBackend):
    name = "aws_kms"

    def __init__(self, key_id: Optional[str] = None, client=None):
        self.key_id = key_id if key_id is not None else os.getenv("AWS_KMS_KEY_ID")
        if not self.key_id:
            raise RuntimeError("AWS_KMS_KEY_ID must be set for the AWS KMS backend")
        if client is not None:
            self._client = client  # real dependency injection point for tests - never a real AWS call in a test
        else:
            import boto3  # lazy: only required when this backend is actually used
            self._client = boto3.client("kms")

    def wrap_dek(self, plaintext_dek: bytes) -> bytes:
        response = self._client.encrypt(KeyId=self.key_id, Plaintext=plaintext_dek)
        return response["CiphertextBlob"]

    def unwrap_dek(self, wrapped_dek: bytes) -> bytes:
        try:
            response = self._client.decrypt(CiphertextBlob=wrapped_dek, KeyId=self.key_id)
        except Exception as e:  # noqa: BLE001 - any real boto3/ClientError here means "cannot decrypt", not a crash
            raise CredentialDecryptionError(f"AWS KMS could not unwrap this DEK: {e}") from e
        return response["Plaintext"]


def get_default_kms_backend() -> KMSBackend:
    """
    CREDENTIAL_VAULT_KMS_BACKEND selects the backend ("local" default, or
    "aws_kms") - a deployment config choice, not something callers should
    hardcode. Defaulting to "local" (not raising when unset) keeps a
    fresh dev checkout usable without any cloud account; production
    deployments set this explicitly, same convention as every other
    "flagged, not silently assumed fine" default in this codebase
    (.env.example documents every one of these).
    """
    backend = (os.getenv("CREDENTIAL_VAULT_KMS_BACKEND") or "local").lower()
    if backend == "local":
        return LocalEnvelopeKMS()
    if backend == "aws_kms":
        return AWSKMSBackend()
    raise ValueError(f"unknown CREDENTIAL_VAULT_KMS_BACKEND: {backend!r} (expected 'local' or 'aws_kms')")


def encrypt_credentials(credentials: dict, kms: KMSBackend) -> str:
    """
    Real envelope encryption: a fresh, random DEK per call (never reused
    across writes - a single leaked DEK then only ever exposes the one
    credential it encrypted), the credentials JSON encrypted with it, and
    the DEK itself wrapped by the KMS backend before either is stored.
    Returns a self-describing JSON string - the real replacement for the
    plaintext JSON connection_credentials_vault used to hold directly.
    """
    if not isinstance(credentials, dict):
        raise ValueError('credentials must be a JSON object, e.g. {"api_key": "..."}')
    plaintext_dek = Fernet.generate_key()
    data_fernet = Fernet(plaintext_dek)
    ciphertext = data_fernet.encrypt(json.dumps(credentials).encode("utf-8"))
    wrapped_dek = kms.wrap_dek(plaintext_dek)
    envelope = {
        "v": _ENVELOPE_VERSION,
        "kms_backend": kms.name,
        "wrapped_dek": base64.b64encode(wrapped_dek).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }
    return json.dumps(envelope)


def decrypt_credentials(envelope_json: str, kms: KMSBackend) -> dict:
    """
    The inverse of encrypt_credentials() - requires the SAME kms backend
    (by name) the envelope was encrypted with; a mismatch fails loud
    (CredentialDecryptionError) rather than attempting a doomed decrypt,
    since a Fernet/AWS-KMS-shaped blob decrypted with the wrong backend
    would just raise its own, more confusing error further down.
    """
    try:
        envelope = json.loads(envelope_json)
    except (TypeError, ValueError) as e:
        raise CredentialDecryptionError(f"not a valid credential envelope: {e}") from e
    if not is_encrypted_envelope(envelope_json):
        raise CredentialDecryptionError(
            "value is not a recognized encrypted envelope (v=1 with wrapped_dek/ciphertext) - "
            "a legacy plaintext credential predating field-level encryption? re-set it with "
            "policy_cli.py set-credentials so it gets encrypted."
        )
    if envelope["kms_backend"] != kms.name:
        raise CredentialDecryptionError(
            f"this envelope was encrypted with KMS backend {envelope['kms_backend']!r}, "
            f"but {kms.name!r} was supplied to decrypt it"
        )
    wrapped_dek = base64.b64decode(envelope["wrapped_dek"])
    ciphertext = base64.b64decode(envelope["ciphertext"])
    plaintext_dek = kms.unwrap_dek(wrapped_dek)
    data_fernet = Fernet(plaintext_dek)
    try:
        plaintext = data_fernet.decrypt(ciphertext)
    except InvalidToken as e:
        raise CredentialDecryptionError("DEK unwrapped successfully but ciphertext failed to decrypt - corrupt envelope?") from e
    return json.loads(plaintext.decode("utf-8"))


def is_encrypted_envelope(value: str) -> bool:
    """
    Detects this module's own envelope format vs. anything else (a
    legacy plaintext JSON credential blob, garbage, empty) - lets a
    caller (data_access.py::load_source()) fail loud and specifically on
    an old, pre-encryption credential rather than silently misreading it
    as {} the way a malformed blob used to degrade. No data migration
    needed for this: no real production credential has ever been stored
    in this repo's own environment (confirmed - see market_scraper
    README's live-credential-verification section), so there is no
    legacy data to migrate, only the theoretical case to fail correctly
    on rather than silently mishandle.
    """
    try:
        obj = json.loads(value) if isinstance(value, str) else None
    except (TypeError, ValueError):
        return False
    return (
        isinstance(obj, dict)
        and obj.get("v") == _ENVELOPE_VERSION
        and obj.get("kms_backend") in ("local", "aws_kms")
        and isinstance(obj.get("wrapped_dek"), str)
        and isinstance(obj.get("ciphertext"), str)
    )


def rewrap_envelope(envelope_json: str, kms: KMSBackend) -> Optional[str]:
    """The same credential with its DEK wrapped under the backend's current
    key, or None when it already is. The encrypted credential itself is not
    touched (only the small wrapped DEK changes), so nothing can be lost:
    a DEK that can't be unwrapped raises CredentialDecryptionError and the
    stored value stays as it was."""
    if not is_encrypted_envelope(envelope_json):
        raise CredentialDecryptionError("not a recognized encrypted envelope")
    envelope = json.loads(envelope_json)
    if envelope["kms_backend"] != kms.name:
        raise CredentialDecryptionError(
            f"envelope uses KMS backend {envelope['kms_backend']!r}, not {kms.name!r}")
    wrapped = base64.b64decode(envelope["wrapped_dek"])
    if isinstance(kms, LocalEnvelopeKMS) and kms.wrapped_with_current_key(wrapped):
        return None
    plaintext_dek = kms.unwrap_dek(wrapped)
    Fernet(plaintext_dek).decrypt(base64.b64decode(envelope["ciphertext"]))  # the credential still opens
    envelope["wrapped_dek"] = base64.b64encode(kms.wrap_dek(plaintext_dek)).decode("ascii")
    return json.dumps(envelope)

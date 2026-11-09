"""
KEEL - object storage adapter (any S3-compatible service: local MinIO, Backblaze B2).

`src.ai.db.minio_client()` returns an `ObjectStore`, which exposes the same
seven Minio methods the code already uses (bucket_exists, make_bucket,
put_object, get_object, stat_object, remove_object, list_objects), so no
call site changes how it stores or reads a file. What it adds:

Single-bucket mode (`MINIO_BUCKET` set; production on Backblaze B2)
    Bucket names are global on hosted services and an application key should
    reach one private bucket only. The code's logical buckets
    (ceopro-rag-knowledge, ceopro-marketing-*, ceopro-extraction-results)
    become the first part of the object key inside that one bucket:
    `ceopro-rag-knowledge/uploads/<tenant_id>/<sha256>.pdf`. Keys already
    start with the tenant id (images) or `uploads/<tenant_id>/` (documents),
    so every object stays under a per-tenant prefix. Keys stored in
    PostgreSQL are unchanged, so moving between modes never rewrites data.
    make_bucket never creates anything here: a missing bucket is a
    configuration error (StorageUnavailable), never a new, possibly public,
    bucket.

    Without `MINIO_BUCKET` (local MinIO, CI) each logical bucket is a real
    bucket, exactly as before.

Limits, so a free tier is never exceeded silently
    STORAGE_MAX_OBJECT_BYTES (default 25 MiB) refuses any single larger
    object. STORAGE_QUOTA_BYTES (default 9 GB in single-bucket mode, below
    B2's 10 GB free storage; unset = no total limit locally) refuses a write
    that would take the stored total past it. The total comes from listing
    the bucket at most once per STORAGE_USAGE_TTL_SECONDS (default 600) per
    process, plus this process's own writes since. The provider's own
    caps (B2 "Caps & Alerts", all set to $0) are the hard backstop: their
    "cap exceeded" refusals are reported as StorageQuotaExceeded too.

Clear errors
    StorageQuotaExceeded (HTTP 507) and StorageUnavailable (HTTP 503) are
    registered as global exception handlers (core/exceptions.py), with a
    plain message and no bucket, key or provider detail. Any other S3 error
    (NoSuchKey, ...) is raised unchanged, so existing not-found handling
    keeps working.

TLS
    Where KEEL is deployed (SENTRY_ENVIRONMENT staging/production) the
    endpoint must be https; the client refuses a plain-http remote endpoint
    rather than send keys and customer files unencrypted.
"""
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator, Optional, Tuple
from urllib.parse import urlparse

from minio import Minio
from minio.error import MinioException, S3Error, ServerError

DEFAULT_MAX_OBJECT_BYTES = 25 * 1024 * 1024
# B2's free allowance is 10 GB (decimal). Leave a margin for overwrites
# counted twice and for writes from other processes inside one usage window.
DEFAULT_SINGLE_BUCKET_QUOTA_BYTES = 9_000_000_000
DEFAULT_USAGE_TTL_SECONDS = 600
_B2_HOST = re.compile(r"^s3\.([a-z0-9-]+)\.backblazeb2\.com$")
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1", "0.0.0.0")


class StorageError(RuntimeError):
    status_code = 503
    public_message = "File storage is unavailable right now. Please try again later."

    def as_http(self):
        from fastapi import HTTPException

        return HTTPException(status_code=self.status_code, detail=self.public_message)


class StorageUnavailable(StorageError):
    """Not configured, unreachable, misconfigured (missing bucket, plain http) or failing (5xx)."""


class StorageQuotaExceeded(StorageError):
    """The storage ceiling KEEL is allowed to use is reached (ours or the provider's cap)."""
    status_code = 507
    public_message = "File storage is full, so new files can't be saved right now. Existing files are not affected."


@dataclass(frozen=True)
class StorageSettings:
    endpoint_host: str
    secure: bool
    access_key: str
    secret_key: str
    region: Optional[str]
    bucket: Optional[str]          # single-bucket mode when set
    max_object_bytes: int
    quota_bytes: Optional[int]
    usage_ttl_seconds: int


def _int_env(name: str, default: Optional[int]) -> Optional[int]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise StorageUnavailable(f"{name} must be a whole number of bytes") from exc
    if value <= 0:
        raise StorageUnavailable(f"{name} must be positive")
    return value


def _deployed() -> bool:
    return (os.getenv("SENTRY_ENVIRONMENT") or "").strip().lower() in ("staging", "production")


def endpoint_problem(endpoint: str, is_deployed: bool) -> Optional[str]:
    """Why MINIO_ENDPOINT can't be used, or None. Shared with config_check."""
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    if parsed.scheme not in ("", "http", "https"):
        return "must start with https:// (or http:// for a local server)"
    if parsed.path not in ("", "/") or parsed.query:
        return "must be the service address only, with no path (S3 path-style requests are built by the client)"
    if not parsed.hostname:
        return "has no host name"
    remote = parsed.hostname not in _LOCAL_HOSTS
    if is_deployed and remote and parsed.scheme != "https":
        return "must use https:// where KEEL is deployed - keys and customer files must not travel unencrypted"
    return None


def load_settings() -> StorageSettings:
    endpoint = (os.getenv("MINIO_ENDPOINT") or "").strip()
    access_key = (os.getenv("MINIO_ROOT_USER") or "").strip()
    secret_key = (os.getenv("MINIO_ROOT_PASSWORD") or "").strip()
    if not endpoint or not access_key or not secret_key:
        raise StorageUnavailable("MINIO_ENDPOINT/MINIO_ROOT_USER/MINIO_ROOT_PASSWORD must all be set.")
    problem = endpoint_problem(endpoint, _deployed())
    if problem:
        raise StorageUnavailable(f"MINIO_ENDPOINT {problem}")
    parsed = urlparse(endpoint if "://" in endpoint else f"//{endpoint}")
    host = parsed.netloc
    region = (os.getenv("MINIO_REGION") or "").strip() or None
    if region is None:
        match = _B2_HOST.match(parsed.hostname or "")
        region = match.group(1) if match else None
    bucket = (os.getenv("MINIO_BUCKET") or "").strip() or None
    default_quota = DEFAULT_SINGLE_BUCKET_QUOTA_BYTES if bucket else None
    return StorageSettings(
        endpoint_host=host,
        secure=parsed.scheme == "https",
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        bucket=bucket,
        max_object_bytes=_int_env("STORAGE_MAX_OBJECT_BYTES", DEFAULT_MAX_OBJECT_BYTES),
        quota_bytes=_int_env("STORAGE_QUOTA_BYTES", default_quota),
        usage_ttl_seconds=_int_env("STORAGE_USAGE_TTL_SECONDS", DEFAULT_USAGE_TTL_SECONDS),
    )


def _is_cap_error(err: S3Error) -> bool:
    # B2 reports its caps (storage, download, transaction) as 403 with a
    # "... cap exceeded" message; some S3 services use a QuotaExceeded code.
    text = f"{getattr(err, 'code', '') or ''} {getattr(err, 'message', '') or ''}".lower()
    return "cap exceeded" in text or "quotaexceeded" in text.replace(" ", "") or "storage_cap" in text


@dataclass(frozen=True)
class ListedObject:
    object_name: str
    size: Optional[int]
    last_modified: Optional[datetime]
    etag: Optional[str]
    is_dir: bool


# Process-wide usage estimate per storage namespace: (listed_at, bytes listed, bytes written since).
_usage_lock = threading.Lock()
_usage: dict = {}


def reset_usage_cache() -> None:
    with _usage_lock:
        _usage.clear()


class ObjectStore:
    """Duck-types the Minio methods KEEL uses; see the module docstring."""

    def __init__(self, settings: StorageSettings, client: Optional[Minio] = None):
        self.settings = settings
        self.client = client or Minio(
            settings.endpoint_host, access_key=settings.access_key, secret_key=settings.secret_key,
            secure=settings.secure, region=settings.region,
        )
        self._physical_bucket_ok = False

    # --- naming -----------------------------------------------------------------------
    @property
    def single_bucket(self) -> bool:
        return self.settings.bucket is not None

    def _locate(self, bucket: str, key: str) -> Tuple[str, str]:
        if any(part in ("", ".", "..") for part in key.split("/")[:-1]) or not key or key.startswith("/"):
            raise ValueError("Object keys must be relative and must not contain empty, '.' or '..' parts")
        if self.single_bucket:
            return self.settings.bucket, f"{bucket}/{key}"
        return bucket, key

    def _namespace(self) -> str:
        return f"{self.settings.endpoint_host}/{self.settings.bucket or '*'}"

    # --- error translation ------------------------------------------------------------
    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except S3Error as err:
            if _is_cap_error(err):
                raise StorageQuotaExceeded("the storage provider refused the request: cap exceeded") from err
            if getattr(err, "code", "") in ("NoSuchBucket",) and self.single_bucket:
                raise StorageUnavailable("the configured MINIO_BUCKET does not exist") from err
            if getattr(err, "code", "") in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"):
                raise StorageUnavailable(f"the storage provider refused KEEL's key ({err.code})") from err
            raise
        except ServerError as err:
            raise StorageUnavailable(f"the storage service failed (HTTP {getattr(err, 'status_code', '?')})") from err
        except StorageError:
            raise
        except (MinioException, OSError) as err:
            raise StorageUnavailable(f"the storage service could not be reached ({type(err).__name__})") from err
        except Exception as err:  # urllib3 errors (MaxRetryError, ...) don't share a public base with OSError
            if type(err).__module__.startswith("urllib3"):
                raise StorageUnavailable(f"the storage service could not be reached ({type(err).__name__})") from err
            raise

    # --- buckets ----------------------------------------------------------------------
    def _ensure_physical_bucket(self) -> None:
        if self._physical_bucket_ok:
            return
        if not self._call(self.client.bucket_exists, self.settings.bucket):
            raise StorageUnavailable("the configured MINIO_BUCKET does not exist")
        self._physical_bucket_ok = True

    def bucket_exists(self, bucket: str) -> bool:
        if self.single_bucket:
            self._ensure_physical_bucket()
            return True
        return self._call(self.client.bucket_exists, bucket)

    def make_bucket(self, bucket: str, *args, **kwargs) -> None:
        if self.single_bucket:
            self._ensure_physical_bucket()  # never creates one: see module docstring
            return
        self._call(self.client.make_bucket, bucket, *args, **kwargs)

    # --- objects ----------------------------------------------------------------------
    def put_object(self, bucket_name: str, object_name: str, data, length: int, *args, **kwargs):
        if length is None or length < 0:
            raise ValueError("put_object needs the exact object length (streaming uploads are not used)")
        if length > self.settings.max_object_bytes:
            raise StorageQuotaExceeded(f"object of {length} bytes is over STORAGE_MAX_OBJECT_BYTES")
        physical_bucket, physical_key = self._locate(bucket_name, object_name)
        self._check_quota(length)
        result = self._call(self.client.put_object, physical_bucket, physical_key, data, length, *args, **kwargs)
        self._add_usage(length)
        return result

    def get_object(self, bucket_name: str, object_name: str, *args, **kwargs):
        return self._call(self.client.get_object, *self._locate(bucket_name, object_name), *args, **kwargs)

    def stat_object(self, bucket_name: str, object_name: str, *args, **kwargs):
        return self._call(self.client.stat_object, *self._locate(bucket_name, object_name), *args, **kwargs)

    def remove_object(self, bucket_name: str, object_name: str, *args, **kwargs):
        return self._call(self.client.remove_object, *self._locate(bucket_name, object_name), *args, **kwargs)

    def list_objects(self, bucket_name: str, prefix: Optional[str] = None, recursive: bool = False,
                     **kwargs) -> Iterator[ListedObject]:
        if not self.single_bucket:
            yield from self._iterate(self.client.list_objects, bucket_name, prefix=prefix, recursive=recursive, **kwargs)
            return
        logical = f"{bucket_name}/"
        for obj in self._iterate(self.client.list_objects, self.settings.bucket,
                                 prefix=logical + (prefix or ""), recursive=recursive, **kwargs):
            if not obj.object_name.startswith(logical):
                continue
            yield ListedObject(obj.object_name[len(logical):], obj.size, obj.last_modified, obj.etag, obj.is_dir)

    def _iterate(self, fn, *args, **kwargs):
        iterator = self._call(fn, *args, **kwargs)
        while True:
            try:
                obj = self._call(next, iterator)
            except StopIteration:
                return
            yield obj

    # --- usage and quota --------------------------------------------------------------
    def _list_total_bytes(self) -> int:
        if self.single_bucket:
            buckets = [self.settings.bucket]
        else:
            buckets = [b.name for b in self._call(self.client.list_buckets)]
        total = 0
        for name in buckets:
            for obj in self._iterate(self.client.list_objects, name, recursive=True):
                total += int(obj.size or 0)
        return total

    def used_bytes(self, refresh: bool = False) -> int:
        key = self._namespace()
        now = time.monotonic()
        with _usage_lock:
            cached = _usage.get(key)
        if refresh or cached is None or now - cached[0] > self.settings.usage_ttl_seconds:
            listed = self._list_total_bytes()
            with _usage_lock:
                _usage[key] = (now, listed, 0)
            return listed
        return cached[1] + cached[2]

    def _check_quota(self, length: int) -> None:
        quota = self.settings.quota_bytes
        if quota is None:
            return
        used = self.used_bytes()
        if used + length > quota:
            used = self.used_bytes(refresh=True)  # deletions since the last listing may have freed space
            if used + length > quota:
                raise StorageQuotaExceeded(f"write of {length} bytes would pass STORAGE_QUOTA_BYTES")

    def _add_usage(self, length: int) -> None:
        key = self._namespace()
        with _usage_lock:
            cached = _usage.get(key)
            if cached is not None:
                _usage[key] = (cached[0], cached[1], cached[2] + length)

    def usage_summary(self) -> dict:
        """For /health/storage: no names, keys or byte counts of individual tenants."""
        used = self.used_bytes()
        quota = self.settings.quota_bytes
        return {
            "mode": "single_bucket" if self.single_bucket else "bucket_per_kind",
            "used_percent": round(100 * used / quota, 1) if quota else None,
            "quota_gb": round(quota / 1e9, 2) if quota else None,
        }


def object_store() -> ObjectStore:
    return ObjectStore(load_settings())

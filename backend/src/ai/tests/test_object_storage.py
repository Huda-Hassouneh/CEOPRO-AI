"""core/object_storage.py: single-bucket naming, limits, clear errors, TLS rule.

The offline tests use a fake Minio client. The `real MinIO` tests run against
the disposable server CI builds from Dockerfile.minio (AI_TEST_MINIO_*), in
single-bucket mode exactly as production uses Backblaze B2.
"""
import io
import os
import uuid

import pytest
from minio import Minio
from minio.error import S3Error

from src.ai.core import object_storage as storage
from src.ai.rag import data_access


def _settings(**overrides):
    values = dict(endpoint_host="storage.test", secure=True, access_key="k", secret_key="s", region=None,
                  bucket="keel-files", max_object_bytes=1000, quota_bytes=5000, usage_ttl_seconds=600)
    values.update(overrides)
    return storage.StorageSettings(**values)


class _Obj:
    def __init__(self, name, size):
        self.object_name, self.size, self.last_modified, self.etag, self.is_dir = name, size, None, None, False


class _FakeMinio:
    def __init__(self, buckets=("keel-files",)):
        self.buckets = set(buckets)
        self.objects = {}
        self.made = []

    def bucket_exists(self, bucket):
        return bucket in self.buckets

    def make_bucket(self, bucket):
        self.made.append(bucket)
        self.buckets.add(bucket)

    def put_object(self, bucket, key, data, length, **kwargs):
        if bucket not in self.buckets:
            raise S3Error(None, "NoSuchBucket", "missing", bucket, None, None)
        self.objects[(bucket, key)] = data.read()

    def list_objects(self, bucket, prefix=None, recursive=False):
        for (b, key), body in list(self.objects.items()):
            if b == bucket and key.startswith(prefix or ""):
                yield _Obj(key, len(body))

    def remove_object(self, bucket, key):
        self.objects.pop((bucket, key), None)

    def list_buckets(self):
        return [type("B", (), {"name": name}) for name in self.buckets]


@pytest.fixture(autouse=True)
def _fresh_usage():
    storage.reset_usage_cache()
    yield
    storage.reset_usage_cache()


def test_single_bucket_mode_maps_logical_buckets_to_prefixes_and_never_creates_buckets():
    fake = _FakeMinio()
    store = storage.ObjectStore(_settings(), client=fake)
    assert store.bucket_exists("ceopro-rag-knowledge") is True
    store.make_bucket("ceopro-rag-knowledge")
    assert fake.made == []
    store.put_object("ceopro-rag-knowledge", "uploads/t1/a.pdf", io.BytesIO(b"abc"), 3)
    assert ("keel-files", "ceopro-rag-knowledge/uploads/t1/a.pdf") in fake.objects
    listed = [o.object_name for o in store.list_objects("ceopro-rag-knowledge", prefix="uploads/t1/", recursive=True)]
    assert listed == ["uploads/t1/a.pdf"]


def test_missing_configured_bucket_is_a_clear_unavailable_error_not_a_new_bucket():
    fake = _FakeMinio(buckets=())
    store = storage.ObjectStore(_settings(), client=fake)
    with pytest.raises(storage.StorageUnavailable):
        store.make_bucket("ceopro-rag-knowledge")
    assert fake.made == [] and fake.buckets == set()


def test_object_size_and_total_quota_are_enforced_before_the_write():
    fake = _FakeMinio()
    store = storage.ObjectStore(_settings(max_object_bytes=1000, quota_bytes=2500), client=fake)
    with pytest.raises(storage.StorageQuotaExceeded):
        store.put_object("b", "t1/big.bin", io.BytesIO(b"x" * 1001), 1001)
    store.put_object("b", "t1/one.bin", io.BytesIO(b"x" * 1000), 1000)
    store.put_object("b", "t1/two.bin", io.BytesIO(b"x" * 1000), 1000)
    with pytest.raises(storage.StorageQuotaExceeded) as refused:
        store.put_object("b", "t1/three.bin", io.BytesIO(b"x" * 1000), 1000)
    assert refused.value.as_http().status_code == 507
    assert len(fake.objects) == 2
    # Space freed since the last listing is found again (a refusal re-lists before refusing).
    store.remove_object("b", "t1/one.bin")
    store.put_object("b", "t1/three.bin", io.BytesIO(b"x" * 1000), 1000)


def test_provider_cap_refusals_become_storage_full_and_other_errors_stay_unchanged():
    class _Capped(_FakeMinio):
        def put_object(self, *args, **kwargs):
            raise S3Error(None, "AccessDenied", "Cannot upload files, storage cap exceeded.", "r", "req", "host")

        def get_object(self, bucket, key):
            raise S3Error(None, "NoSuchKey", "not found", key, "req", "host")

    store = storage.ObjectStore(_settings(quota_bytes=None), client=_Capped())
    with pytest.raises(storage.StorageQuotaExceeded):
        store.put_object("b", "t1/a", io.BytesIO(b"a"), 1)
    with pytest.raises(S3Error) as missing:
        store.get_object("b", "t1/a")
    assert missing.value.code == "NoSuchKey"  # existing not-found handling keeps working


def test_unreachable_storage_is_unavailable():
    import urllib3

    client = Minio("127.0.0.1:9", access_key="k", secret_key="s", secure=False,
                   http_client=urllib3.PoolManager(retries=urllib3.Retry(total=0), timeout=1))
    store = storage.ObjectStore(_settings(endpoint_host="127.0.0.1:9", secure=False, quota_bytes=None, bucket=None),
                                client=client)
    with pytest.raises(storage.StorageUnavailable):
        store.bucket_exists("anything")


@pytest.mark.parametrize("key", ["", "/abs", "a/../b", "a//b", "./a"])
def test_keys_that_could_escape_a_prefix_are_refused(key):
    store = storage.ObjectStore(_settings(), client=_FakeMinio())
    with pytest.raises(ValueError):
        store.put_object("b", key, io.BytesIO(b"a"), 1)


def test_endpoint_rules():
    assert storage.endpoint_problem("https://s3.us-west-004.backblazeb2.com", True) is None
    assert "https" in storage.endpoint_problem("http://s3.us-west-004.backblazeb2.com", True)
    assert storage.endpoint_problem("http://minio:9000", False) is None
    assert storage.endpoint_problem("http://localhost:9000", True) is None
    assert "path" in storage.endpoint_problem("https://abc.supabase.co/storage/v1/s3", True)


def test_settings_from_environment(monkeypatch):
    monkeypatch.setenv("MINIO_ENDPOINT", "https://s3.eu-central-003.backblazeb2.com")
    monkeypatch.setenv("MINIO_ROOT_USER", "id")
    monkeypatch.setenv("MINIO_ROOT_PASSWORD", "secret")
    monkeypatch.setenv("MINIO_BUCKET", "keel-prod-files")
    for name in ("MINIO_REGION", "STORAGE_QUOTA_BYTES", "STORAGE_MAX_OBJECT_BYTES"):
        monkeypatch.delenv(name, raising=False)
    settings = storage.load_settings()
    assert settings.secure and settings.region == "eu-central-003" and settings.bucket == "keel-prod-files"
    assert settings.quota_bytes == storage.DEFAULT_SINGLE_BUCKET_QUOTA_BYTES < 10_000_000_000
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "production")
    monkeypatch.setenv("MINIO_ENDPOINT", "http://s3.eu-central-003.backblazeb2.com")
    with pytest.raises(storage.StorageUnavailable):
        storage.load_settings()
    monkeypatch.delenv("MINIO_ENDPOINT")
    with pytest.raises(RuntimeError):  # existing callers catch RuntimeError for "not configured"
        storage.load_settings()


def test_assistant_summary_objects_are_per_tenant_while_row_paths_keep_their_slot():
    assert data_access.storage_object_key("t1", "_generated/sales_history.txt") == "_generated/t1/sales_history.txt"
    assert data_access.storage_object_key("t2", "_generated/sales_history.txt") == "_generated/t2/sales_history.txt"
    assert data_access.storage_object_key("t1", "uploads/t1/abc.pdf") == "uploads/t1/abc.pdf"


# --- real MinIO (single-bucket mode, like production on B2) ------------------------------

MINIO = os.getenv("AI_TEST_MINIO_ENDPOINT")
real_minio = pytest.mark.skipif(not MINIO, reason="disposable MinIO (AI_TEST_MINIO_*) is required")


@pytest.fixture
def real_store():
    access, secret = os.environ["AI_TEST_MINIO_ACCESS_KEY"], os.environ["AI_TEST_MINIO_SECRET_KEY"]
    raw = Minio(MINIO, access_key=access, secret_key=secret, secure=False)
    bucket = f"keel-test-{uuid.uuid4().hex[:12]}"
    raw.make_bucket(bucket)  # private by default: no bucket policy
    store = storage.ObjectStore(_settings(endpoint_host=MINIO, secure=False, access_key=access, secret_key=secret,
                                          bucket=bucket, max_object_bytes=10_000, quota_bytes=20_000), client=raw)
    yield store
    for obj in raw.list_objects(bucket, recursive=True):
        raw.remove_object(bucket, obj.object_name)
    raw.remove_bucket(bucket)


@real_minio
def test_real_minio_round_trip_tenant_prefixes_and_private_bucket(real_store):
    import httpx

    real_store.make_bucket("ceopro-marketing-generated-images")
    real_store.put_object("ceopro-marketing-generated-images", "tenant-a/c1/x.png", io.BytesIO(b"A" * 10), 10,
                          content_type="image/png")
    real_store.put_object("ceopro-marketing-generated-images", "tenant-b/c2/y.png", io.BytesIO(b"B" * 10), 10)
    response = real_store.get_object("ceopro-marketing-generated-images", "tenant-a/c1/x.png")
    try:
        assert response.read() == b"A" * 10
    finally:
        response.close()
        response.release_conn()
    mine = [o.object_name for o in real_store.list_objects("ceopro-marketing-generated-images",
                                                           prefix="tenant-a/", recursive=True)]
    assert mine == ["tenant-a/c1/x.png"]
    # The bucket is private: an unsigned request can neither read nor list.
    base = f"http://{MINIO}/{real_store.settings.bucket}"
    assert httpx.get(f"{base}/ceopro-marketing-generated-images/tenant-a/c1/x.png").status_code == 403
    assert httpx.get(f"{base}?list-type=2").status_code == 403
    with pytest.raises(S3Error):
        real_store.stat_object("ceopro-marketing-generated-images", "tenant-a/c1/missing.png")


@real_minio
def test_real_minio_quota_refuses_and_stores_nothing(real_store):
    real_store.put_object("ceopro-rag-knowledge", "uploads/t/a.txt", io.BytesIO(b"x" * 9_000), 9_000)
    real_store.put_object("ceopro-rag-knowledge", "uploads/t/b.txt", io.BytesIO(b"x" * 9_000), 9_000)
    with pytest.raises(storage.StorageQuotaExceeded):
        real_store.put_object("ceopro-rag-knowledge", "uploads/t/c.txt", io.BytesIO(b"x" * 9_000), 9_000)
    names = [o.object_name for o in real_store.list_objects("ceopro-rag-knowledge", recursive=True)]
    assert sorted(names) == ["uploads/t/a.txt", "uploads/t/b.txt"]
    assert real_store.usage_summary()["used_percent"] == 90.0


def test_a_capped_or_failed_usage_listing_never_refuses_writes_as_storage_full():
    """Regression (Session 2 review): B2 refusing the LISTING (daily Class C cap) made every upload 507."""
    class _ListingCapped(_FakeMinio):
        capped = False

        def list_objects(self, bucket, prefix=None, recursive=False):
            if self.capped:
                raise S3Error(None, "AccessDenied", "Transaction cap exceeded.", bucket, "req", "host")
            return super().list_objects(bucket, prefix=prefix, recursive=recursive)

    fake = _ListingCapped()
    store = storage.ObjectStore(_settings(quota_bytes=5000, usage_ttl_seconds=0), client=fake)
    store.put_object("b", "t1/a", io.BytesIO(b"x" * 100), 100)
    fake.capped = True
    store.put_object("b", "t1/b", io.BytesIO(b"x" * 100), 100)  # last known usage, not "full"
    assert len(fake.objects) == 2
    # Real fullness is still enforced from the last known figure.
    storage.reset_usage_cache()
    fake.capped = False
    fake.objects[("keel-files", "b/t1/big")] = b"x" * 4900
    store.used_bytes(refresh=True)
    fake.capped = True
    with pytest.raises(storage.StorageQuotaExceeded):
        store.put_object("b", "t1/c", io.BytesIO(b"x" * 100), 100)
    # With no figure at all, a failed listing lets the write through (the provider cap is the backstop).
    storage.reset_usage_cache()
    store.put_object("b", "t1/d", io.BytesIO(b"x" * 10), 10)

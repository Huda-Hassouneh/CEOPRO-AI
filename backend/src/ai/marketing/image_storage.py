"""
KEEL - Marketing Campaign Image Storage (source uploads, background-
removed processed versions, and AI-generated creative).

Same MinIO put_object/bucket-scoped pattern extraction/minio_persistence.py
already established for extraction result documents - reused here for
three kinds of object (an uploaded source product image, its optional
background-removed version, and an AI-generated campaign image) rather
than inventing a second storage convention. Uploaded source images are
still never analyzed for text/copy generation - no vision/language-
grounded-on-image model exists in this repo (see
marketing/content_generator.py's own note on that gap); background
removal (marketing/background_removal.py) is a real image-processing step,
not text understanding, and is the one thing that does read the pixels.
"""
import io
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple

from minio import Minio
from minio.error import S3Error

SOURCE_IMAGES_BUCKET = "ceopro-marketing-source-images"
GENERATED_IMAGES_BUCKET = "ceopro-marketing-generated-images"
PROCESSED_IMAGES_BUCKET = "ceopro-marketing-processed-images"
logger = logging.getLogger(__name__)
PreUploadCallback = Callable[[str, str, int], None]


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def new_image_object_key(tenant_id: str, campaign_id: str, ext: str) -> str:
    """Create a tenant-scoped key callers can record before the remote write."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{tenant_id}/{campaign_id}/{ts}_{uuid.uuid4().hex}{ext}"


def _validate_object_key(tenant_id: str, campaign_id: str, object_key: str) -> None:
    prefix = f"{tenant_id}/{campaign_id}/"
    if (not object_key.startswith(prefix) or object_key == prefix
            or any(part in (".", "..") for part in object_key.split("/"))):
        raise ValueError("Image object key must remain within its tenant and campaign prefix")


def _cleanup_failed_upload(client: Minio, bucket: str, object_key: str) -> None:
    try:
        remove_image(client, bucket, object_key)
    except Exception:
        # The caller's pre-upload ledger record remains the recovery source.
        logger.exception("Could not clean up image after an ambiguous PUT failure (key=%s)", object_key)


def _upload_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str, ext: str, bucket: str,
    object_key: Optional[str] = None, on_pre_upload: Optional[PreUploadCallback] = None,
) -> str:
    key = object_key or new_image_object_key(tenant_id, campaign_id, ext)
    _validate_object_key(tenant_id, campaign_id, key)
    _ensure_bucket(client, bucket)
    if on_pre_upload is not None:
        on_pre_upload(bucket, key, len(contents))
    try:
        client.put_object(bucket_name=bucket, object_name=key, data=io.BytesIO(contents), length=len(contents),
                          content_type=content_type)
    except Exception as e:
        _cleanup_failed_upload(client, bucket, key)
        if isinstance(e, S3Error):
            raise RuntimeError(f"Failed to persist image to MinIO: {e}") from e
        raise
    return key


def upload_source_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str, ext: str,
    bucket: str = SOURCE_IMAGES_BUCKET, *, object_key: Optional[str] = None,
    on_pre_upload: Optional[PreUploadCallback] = None,
) -> str:
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket, object_key, on_pre_upload)


# content_type -> extension, for the AI-generated image (no user-chosen
# filename to derive an extension from, unlike the upload endpoint).
_EXT_BY_CONTENT_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def new_generated_image_object_key(tenant_id: str, campaign_id: str, content_type: str) -> str:
    return new_image_object_key(tenant_id, campaign_id, _EXT_BY_CONTENT_TYPE.get(content_type, ".png"))


def new_processed_image_object_key(tenant_id: str, campaign_id: str, content_type: str) -> str:
    return new_image_object_key(tenant_id, campaign_id, _EXT_BY_CONTENT_TYPE.get(content_type, ".png"))


def upload_generated_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str,
    bucket: str = GENERATED_IMAGES_BUCKET, *, object_key: Optional[str] = None,
    on_pre_upload: Optional[PreUploadCallback] = None,
) -> str:
    ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".png")
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket, object_key, on_pre_upload)


def upload_processed_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str,
    bucket: str = PROCESSED_IMAGES_BUCKET, *, object_key: Optional[str] = None,
    on_pre_upload: Optional[PreUploadCallback] = None,
) -> str:
    """The background-removed version of a tenant's own source upload -
    always PNG (rembg's own output format, alpha transparency where the
    background was) regardless of the original upload's format."""
    ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".png")
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket, object_key, on_pre_upload)


def get_image(client: Minio, bucket: str, key: str) -> Tuple[bytes, str]:
    """Reads a stored image back for the GET .../image endpoint to stream
    to the frontend - the one retrieval path this module needed, since
    every write above only ever produced a key, never served the bytes
    back out again."""
    response = client.get_object(bucket, key)
    try:
        return response.read(), response.headers.get("content-type", "application/octet-stream")
    finally:
        response.close()
        response.release_conn()


ALL_BUCKETS = (SOURCE_IMAGES_BUCKET, PROCESSED_IMAGES_BUCKET, GENERATED_IMAGES_BUCKET)


def remove_image(client: Minio, bucket: str, key: str) -> bool:
    """Best effort: a file that is already gone is not an error."""
    try:
        client.remove_object(bucket, key)
    except S3Error as e:
        if getattr(e, "code", "") not in ("NoSuchKey", "NoSuchObject"):
            raise
    return True


def object_exists(client: Minio, bucket: str, key: str) -> bool:
    """Return False only for an object-specific not-found response.

    A missing bucket or storage outage is inconclusive and must preserve its
    ledger row.
    """
    try:
        client.stat_object(bucket, key)
        return True
    except S3Error as e:
        if getattr(e, "code", "") in ("NoSuchKey", "NoSuchObject"):
            return False
        raise


def remove_campaign_images(client: Minio, tenant_id: str, campaign_id: str) -> list:
    """Deletes every stored image of one campaign (uploads, background-removed
    versions, generated images, including earlier ones). Returns the
    (bucket, key) pairs removed."""
    removed = []
    for bucket in ALL_BUCKETS:
        if not client.bucket_exists(bucket):
            continue
        for obj in client.list_objects(bucket, prefix=f"{tenant_id}/{campaign_id}/", recursive=True):
            remove_image(client, bucket, obj.object_name)
            removed.append((bucket, obj.object_name))
    return removed

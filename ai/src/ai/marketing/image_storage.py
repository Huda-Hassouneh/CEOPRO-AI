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
import uuid
from datetime import datetime, timezone
from typing import Tuple

from minio import Minio
from minio.error import S3Error

SOURCE_IMAGES_BUCKET = "ceopro-marketing-source-images"
GENERATED_IMAGES_BUCKET = "ceopro-marketing-generated-images"
PROCESSED_IMAGES_BUCKET = "ceopro-marketing-processed-images"


def _ensure_bucket(client: Minio, bucket: str) -> None:
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def _upload_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str, ext: str, bucket: str,
) -> str:
    _ensure_bucket(client, bucket)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    key = f"{tenant_id}/{campaign_id}/{ts}_{uuid.uuid4().hex}{ext}"
    try:
        client.put_object(
            bucket_name=bucket, object_name=key, data=io.BytesIO(contents), length=len(contents),
            content_type=content_type,
        )
    except S3Error as e:
        raise RuntimeError(f"Failed to persist image to MinIO: {e}") from e
    return key


def upload_source_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str, ext: str,
    bucket: str = SOURCE_IMAGES_BUCKET,
) -> str:
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket)


# content_type -> extension, for the AI-generated image (no user-chosen
# filename to derive an extension from, unlike the upload endpoint).
_EXT_BY_CONTENT_TYPE = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def upload_generated_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str,
    bucket: str = GENERATED_IMAGES_BUCKET,
) -> str:
    ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".png")
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket)


def upload_processed_image(
    client: Minio, contents: bytes, content_type: str, tenant_id: str, campaign_id: str,
    bucket: str = PROCESSED_IMAGES_BUCKET,
) -> str:
    """The background-removed version of a tenant's own source upload -
    always PNG (rembg's own output format, alpha transparency where the
    background was) regardless of the original upload's format."""
    ext = _EXT_BY_CONTENT_TYPE.get(content_type, ".png")
    return _upload_image(client, contents, content_type, tenant_id, campaign_id, ext, bucket)


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


def remove_image(client: Minio, bucket: str, key: str) -> None:
    """Best effort: a file that is already gone is not an error."""
    try:
        client.remove_object(bucket, key)
    except S3Error as e:
        if getattr(e, "code", "") not in ("NoSuchKey", "NoSuchBucket"):
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

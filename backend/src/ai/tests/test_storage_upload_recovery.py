import unittest
from unittest.mock import Mock

from minio.error import S3Error

from src.ai.extraction.minio_persistence import (
    EXTRACTION_RESULTS_BUCKET,
    new_extraction_object_key,
    object_exists as extraction_object_exists,
    upload_extraction_document,
)
from src.ai.marketing.image_storage import (
    SOURCE_IMAGES_BUCKET,
    new_image_object_key,
    object_exists as marketing_object_exists,
    remove_image,
    upload_source_image,
)


class StorageUploadRecoveryTests(unittest.TestCase):
    @staticmethod
    def _s3_error(code):
        return S3Error(None, code, "test", "", "", "")

    def test_image_tracks_key_before_put_and_reuses_key_for_retry(self):
        client = Mock()
        client.bucket_exists.return_value = True
        events = []
        client.put_object.side_effect = lambda **kwargs: events.append(("put", kwargs["object_name"]))
        key = new_image_object_key("tenant-a", "campaign-1", ".png")
        track = lambda bucket, object_key, size: events.append(("tracked", bucket, object_key, size))

        for _ in range(2):
            self.assertEqual(
                upload_source_image(
                    client, b"image", "image/png", "tenant-a", "campaign-1", ".png",
                    object_key=key, on_pre_upload=track,
                ),
                key,
            )

        self.assertEqual(
            events,
            [
                ("tracked", SOURCE_IMAGES_BUCKET, key, 5),
                ("put", key),
                ("tracked", SOURCE_IMAGES_BUCKET, key, 5),
                ("put", key),
            ],
        )

    def test_image_rejects_cross_tenant_key_before_remote_write(self):
        client = Mock()
        client.bucket_exists.return_value = True
        with self.assertRaises(ValueError):
            upload_source_image(
                client, b"x", "image/png", "tenant-a", "campaign-1", ".png",
                object_key="tenant-b/campaign-1/foreign.png",
            )
        client.put_object.assert_not_called()

    def test_image_cleans_up_ambiguous_put_failure_without_masking_it(self):
        client = Mock()
        client.bucket_exists.return_value = True
        client.put_object.side_effect = OSError("connection dropped after request")
        client.remove_object.side_effect = OSError("storage unavailable")
        key = "tenant-a/campaign-1/retry.png"

        with self.assertRaisesRegex(OSError, "connection dropped"):
            upload_source_image(
                client, b"x", "image/png", "tenant-a", "campaign-1", ".png", object_key=key,
            )

        client.remove_object.assert_called_once_with(SOURCE_IMAGES_BUCKET, key)

    def test_pre_upload_tracking_failure_prevents_image_put(self):
        client = Mock()
        client.bucket_exists.return_value = True

        def fail_tracking(*_args):
            raise RuntimeError("ledger unavailable")

        with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
            upload_source_image(
                client, b"x", "image/png", "tenant-a", "campaign-1", ".png",
                on_pre_upload=fail_tracking,
            )
        client.put_object.assert_not_called()

    def test_extraction_tracks_before_put_and_reuses_key_for_retry(self):
        client = Mock()
        client.bucket_exists.return_value = True
        events = []
        client.put_object.side_effect = lambda **kwargs: events.append(("put", kwargs["object_name"]))
        key = new_extraction_object_key("tenant-a", "job-1")
        track = lambda bucket, object_key, size: events.append(("tracked", bucket, object_key, size))

        for _ in range(2):
            self.assertEqual(
                upload_extraction_document(
                    client, {"tenant_id": "tenant-a"}, "tenant-a", "job-1",
                    object_key=key, on_pre_upload=track,
                ),
                key,
            )

        self.assertEqual([event[0] for event in events], ["tracked", "put", "tracked", "put"])
        self.assertEqual([event[2] if event[0] == "tracked" else event[1] for event in events], [key] * 4)

    def test_extraction_rejects_foreign_key_and_cleans_ambiguous_put_failure(self):
        client = Mock()
        client.bucket_exists.return_value = True
        with self.assertRaises(ValueError):
            upload_extraction_document(
                client, {}, "tenant-a", "job-1", object_key="tenant-b/job-1/foreign.json",
            )
        client.put_object.assert_not_called()

        key = "tenant-a/job-1/retry.json"
        client.put_object.side_effect = OSError("ambiguous upload")
        with self.assertRaisesRegex(OSError, "ambiguous upload"):
            upload_extraction_document(client, {}, "tenant-a", "job-1", object_key=key)
        client.remove_object.assert_called_once_with(EXTRACTION_RESULTS_BUCKET, key)

    def test_extraction_tracking_failure_prevents_remote_write(self):
        client = Mock()
        client.bucket_exists.return_value = True

        def fail_tracking(*_args):
            raise RuntimeError("ledger unavailable")

        with self.assertRaisesRegex(RuntimeError, "ledger unavailable"):
            upload_extraction_document(
                client, {}, "tenant-a", "job-1", on_pre_upload=fail_tracking,
            )
        client.put_object.assert_not_called()

    def test_object_not_found_is_confirmed_but_missing_bucket_is_inconclusive(self):
        client = Mock()
        client.stat_object.side_effect = self._s3_error("NoSuchKey")
        self.assertFalse(marketing_object_exists(client, SOURCE_IMAGES_BUCKET, "tenant-a/key"))
        self.assertFalse(extraction_object_exists(client, EXTRACTION_RESULTS_BUCKET, "tenant-a/key"))

        client.stat_object.side_effect = self._s3_error("NoSuchBucket")
        with self.assertRaises(S3Error):
            marketing_object_exists(client, SOURCE_IMAGES_BUCKET, "tenant-a/key")
        with self.assertRaises(S3Error):
            extraction_object_exists(client, EXTRACTION_RESULTS_BUCKET, "tenant-a/key")
        client.remove_object.side_effect = self._s3_error("NoSuchBucket")
        with self.assertRaises(S3Error):
            remove_image(client, SOURCE_IMAGES_BUCKET, "tenant-a/key")

if __name__ == "__main__":
    unittest.main()

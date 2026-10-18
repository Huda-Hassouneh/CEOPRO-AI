"""Bounded plain/gzip response decoding, independent of competitor workers."""
import gzip
import io


def decode_document(raw, max_bytes=2 * 1024 * 1024):
    if raw.startswith(b"\x1f\x8b"):
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError("DOCUMENT_TOO_LARGE")
    return raw.decode("utf-8-sig", errors="replace")

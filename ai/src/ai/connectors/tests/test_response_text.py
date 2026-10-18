import gzip
import pytest
from src.ai.connectors.response_text import decode_document

def test_plain_and_gzip_response_decoding():
    text = "PC accessories كيل"
    raw = text.encode("utf-8-sig")
    assert decode_document(raw) == text
    assert decode_document(gzip.compress(raw)) == text

@pytest.mark.parametrize("raw", [b"x" * 100, gzip.compress(b"x" * 100)])
def test_response_size_is_bounded_after_decompression(raw):
    with pytest.raises(ValueError, match="DOCUMENT_TOO_LARGE"):
        decode_document(raw, max_bytes=50)

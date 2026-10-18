"""
KEEL - safety checks for Office Open XML uploads (.xlsx/.xlsm/.docx).

These formats are zip archives. A file within the upload size limit can
unpack to gigabytes (a "zip bomb"): measured on this service, an 8 MB
.xlsx that unpacks to 2 GB held an upload request for over ten minutes at
2.3 GB of memory and climbing. Checking the archive's declared unpacked size
before any parser touches it costs milliseconds.

MAX_OFFICE_UNPACKED_MB (default 256) is far above real business files: a
10 MB Excel export typically unpacks to 50-100 MB.
"""
import io
import os
import zipfile

MAX_OFFICE_UNPACKED_MB = int(os.getenv("MAX_OFFICE_UNPACKED_MB", "256"))


class InvalidOfficeFileError(ValueError):
    """The upload is not a usable Office file; the message is safe to show
    to the person who uploaded it."""


def ensure_safe_office_archive(source) -> None:
    """source: a file path or the file's bytes."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
        unpacked = sum(member.file_size for member in archive.infolist())
    except zipfile.BadZipFile:  # a missing file still raises FileNotFoundError, as before
        raise InvalidOfficeFileError(
            "This file isn't a valid Excel or Word file. Open it in Excel/Word, save it again and re-upload, or export it as CSV."
        )
    if unpacked > MAX_OFFICE_UNPACKED_MB * 1024 * 1024:
        raise InvalidOfficeFileError(
            f"This file expands to {unpacked / 1048576:,.0f} MB when opened, above the {MAX_OFFICE_UNPACKED_MB} MB limit. "
            "Split it into smaller files or export it as CSV."
        )

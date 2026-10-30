"""Tenant-bound MPI capabilities; implementations use the caller's transaction.

All calls may propagate existing access/database errors unchanged. None commit,
roll back, close connections, or change tenant context. Bind only to the
established authenticated tenant; subject validation precedes reads/writes.
"""
from typing import Optional, Protocol


class SubjectValidator(Protocol):
    """READ subject existence/ownership; return None or raise existing errors."""

    def __call__(self, subject_type: str, subject_id: Optional[str] = None) -> None: ...


class CountryReader(Protocol):
    """READ subject country context; None means no country is available."""

    def __call__(self, subject_type: str, subject_id: Optional[str] = None) -> Optional[str]: ...


class ReviewReader(Protocol):
    """READ eligible analyzed reviews for a subject; empty list means no input."""

    def __call__(self, subject_type: str, subject_id: Optional[str] = None) -> list: ...


class EvidenceWriter(Protocol):
    """WRITE one evidence row, returning its ID; classification belongs to MPI."""

    def __call__(
        self, category: str, source_module: str, source_record_ids: dict,
        confidence_score: Optional[float], explanation_text: str,
        model_version: Optional[str], country_context: Optional[str] = None,
    ) -> str: ...


class HistoryReader(Protocol):
    """READ ordered evidence rows; empty list is valid, limit is the fetch count."""

    def __call__(
        self, subject_type: str, canonical_subject: Optional[str], limit: int, offset: int,
    ) -> list: ...

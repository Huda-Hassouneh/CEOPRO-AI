"""MPI operations over the existing implementation and caller-owned connection.

Delivery retains connection cleanup and its commits. Summary delegates to the
pipeline, including its durable evidence commit; history performs reads only.
"""
import uuid
from typing import Optional

from src.ai.mpi import pipeline, postgres
from src.ai.mpi.ports import HistoryReader, SubjectValidator


def compute_summary(
    conn, tenant_id: str, subject_type: str, subject_id: Optional[str] = None,
) -> dict:
    """Compute and persist a summary for the established authenticated tenant."""
    return pipeline.get_subject_mpi(conn, tenant_id, subject_type, subject_id)


def get_history(
    conn, tenant_id: str, subject_type: str, subject_id: Optional[str] = None,
    limit: int = 20, offset: int = 0,
    *, history_reader: Optional[HistoryReader] = None,
    subject_validator: Optional[SubjectValidator] = None,
) -> list:
    """Return validated history rows, including one lookahead row for pagination.

    Delivery validates pagination and serializes rows after its existing commit
    so conversion failures retain their original transaction ordering.
    """
    if subject_validator is None:
        subject_validator = postgres.subject_validator(conn, tenant_id)
    subject_validator(subject_type, subject_id)
    canonical_subject = None if subject_type == 'BUSINESS' else str(uuid.UUID(subject_id))
    if history_reader is None:
        history_reader = postgres.history_reader(conn, tenant_id, pipeline.SOURCE_MODULE)
    return history_reader(subject_type, canonical_subject, limit + 1, offset)

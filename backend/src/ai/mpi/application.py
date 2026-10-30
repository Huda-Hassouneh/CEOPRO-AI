"""MPI operations over the existing implementation and caller-owned connection.

Delivery retains connection cleanup and its commits. Summary delegates to the
pipeline, including its durable evidence commit; history performs reads only.
"""
import uuid
from typing import Optional

from src.ai.mpi import data_access, pipeline


def compute_summary(
    conn, tenant_id: str, subject_type: str, subject_id: Optional[str] = None,
) -> dict:
    """Compute and persist a summary for the established authenticated tenant."""
    return pipeline.get_subject_mpi(conn, tenant_id, subject_type, subject_id)


def get_history(
    conn, tenant_id: str, subject_type: str, subject_id: Optional[str] = None,
    limit: int = 20, offset: int = 0,
) -> list:
    """Return validated history rows, including one lookahead row for pagination.

    Delivery validates pagination and serializes rows after its existing commit
    so conversion failures retain their original transaction ordering.
    """
    data_access.validate_subject(conn, tenant_id, subject_type, subject_id)
    canonical_subject = None if subject_type == 'BUSINESS' else str(uuid.UUID(subject_id))
    return data_access.load_history(
        conn, tenant_id, pipeline.SOURCE_MODULE, subject_type, canonical_subject, limit + 1, offset,
    )

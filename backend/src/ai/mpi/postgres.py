"""Default MPI capability composition over the caller's connection and tenant.

Binding performs no I/O. Calls use the existing adapters without committing,
rolling back, closing the connection or changing its tenant context.
"""
from functools import partial

from src.ai.mpi import data_access, evidence
from src.ai.mpi.ports import CountryReader, EvidenceWriter, HistoryReader, ReviewReader, SubjectValidator


def review_reader(conn, tenant_id: str) -> ReviewReader:
    """Bind eligible-review reads to the existing transaction and tenant."""
    return partial(data_access.load_scored_reviews, conn, tenant_id)


def history_reader(conn, tenant_id: str, source_module: str) -> HistoryReader:
    """Bind history reads without taking connection or transaction ownership."""
    return partial(data_access.load_history, conn, tenant_id, source_module)


def evidence_writer(conn, tenant_id: str) -> EvidenceWriter:
    """Bind writes to the caller's tenant transaction; the pipeline commits."""
    return partial(evidence.insert_evidence_record, conn, tenant_id)


def subject_validator(conn, tenant_id: str) -> SubjectValidator:
    """Bind existing subject validation to the authenticated tenant transaction."""
    return partial(data_access.validate_subject, conn, tenant_id)


def country_reader(conn, tenant_id: str) -> CountryReader:
    """Bind existing subject-country lookup to the same tenant transaction."""
    return partial(data_access.load_country_context, conn, tenant_id)

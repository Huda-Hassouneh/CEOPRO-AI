"""Default MPI capability composition over the caller's connection and tenant.

Binding performs no I/O. Calls use the existing adapters without committing,
rolling back, closing the connection or changing its tenant context.
"""
from functools import partial

from src.ai.mpi import data_access
from src.ai.mpi.data_access import history_reader as history_reader, review_reader as review_reader
from src.ai.mpi.evidence import evidence_writer as evidence_writer
from src.ai.mpi.ports import CountryReader, SubjectValidator


def subject_validator(conn, tenant_id: str) -> SubjectValidator:
    """Bind existing subject validation to the authenticated tenant transaction."""
    return partial(data_access.validate_subject, conn, tenant_id)


def country_reader(conn, tenant_id: str) -> CountryReader:
    """Bind existing subject-country lookup to the same tenant transaction."""
    return partial(data_access.load_country_context, conn, tenant_id)

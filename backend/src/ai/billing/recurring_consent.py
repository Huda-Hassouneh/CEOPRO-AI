"""Dormant provider-neutral consent commands; no credential resolution or wiring.

Only a future authenticated collection boundary may own the dedicated socket and
derive tenant/user context. DTOs, challenges and agreement acceptance establish
neither provider readiness nor authority to grant access. Never log challenges.
"""
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum
import uuid

import psycopg2
from src.ai.billing import payment_contracts as C


class ConsentState(str, Enum):
    PENDING_POLICY = 'pending_policy'
    UNSUPPORTED = 'unsupported'
    PRESENTED = 'presented'
    ACCEPTED = 'accepted'
    EXPIRED = 'expired'
    SUPERSEDED = 'superseded'
    WITHDRAWN = 'withdrawn'
    CONFLICT = 'conflict'


class ConsentError(ValueError):
    """Safe category only: do not expose raw SQL, terms or challenges."""


@dataclass(frozen=True)
class PresentationIdentity:
    presentation_id: uuid.UUID
    terms_digest: str

    def __post_init__(self):
        if type(self.presentation_id) is not uuid.UUID:
            raise ConsentError('presentation_uuid_required')
        C._terms_digest(self.terms_digest)


class ConsentRepository:
    """Dedicated restricted connection, never app/admin credentials or role switching.

    Each command commits atomically. Caller authenticates the actor BEFORE it
    sets server-owned context; no command accepts an actor, price or timestamp.
    The NOLOGIN service has no credential/configuration in A1.
    """
    def __init__(self, connection):
        with connection.cursor() as cursor:
            cursor.execute('SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
            if cursor.fetchone() != ('ceopro_consent_service', 'ceopro_consent_service', False, False):
                raise ConsentError('restricted_consent_socket_required')
        self.connection = connection

    def _call(self, statement, arguments):
        category = None
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(statement, arguments)
                result = cursor.fetchone()[0]
            self.connection.commit()
            return C.CustomerPayload.freeze(result)
        except psycopg2.Error as error:
            category = error.pgcode or 'unavailable'
            self.connection.rollback()
        except BaseException:
            with suppress(Exception):
                self.connection.rollback()
            raise
        raise ConsentError('consent_' + category)

    def present(self, attempt_id: uuid.UUID, policy_id: uuid.UUID, *, presentation_id=None) -> C.CustomerPayload:
        return self._call('SELECT public.billing_consent_present(%s,%s,%s)',
                          (str(presentation_id or uuid.uuid4()), str(attempt_id), str(policy_id)))

    def accept(self, presentation: PresentationIdentity, challenge: str, *, acceptance_id=None) -> C.CustomerPayload:
        if type(presentation) is not PresentationIdentity or not isinstance(challenge, str) or len(challenge) != 72:
            raise ConsentError('presentation_challenge_required')
        return self._call('SELECT public.billing_consent_accept(%s,%s,%s,%s)',
                          (str(acceptance_id or uuid.uuid4()), str(presentation.presentation_id), challenge, presentation.terms_digest))

    def invalidate(self, presentation_id: uuid.UUID, reason: ConsentState) -> C.CustomerPayload:
        if type(reason) is not ConsentState or reason not in (ConsentState.WITHDRAWN, ConsentState.SUPERSEDED):
            raise ConsentError('invalidation_reason_required')
        return self._call('SELECT public.billing_consent_invalidate(%s,%s)', (str(presentation_id), reason.value))

    def associate(self, acceptance_id: uuid.UUID, operation_id: uuid.UUID) -> C.CustomerPayload:
        return self._call('SELECT public.billing_consent_associate(%s,%s)', (str(acceptance_id), str(operation_id)))

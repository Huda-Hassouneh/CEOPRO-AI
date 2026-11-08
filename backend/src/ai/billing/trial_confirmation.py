"""Dormant B4 commands. DTOs are data; dedicated DB identities are authority.

No credential resolution, provider calls, runtime registration or consent writer.
Local consent must originate in a separately approved collection boundary.
"""
from contextlib import suppress
import uuid

import psycopg2
from psycopg2.extras import Json
from src.ai.billing import payment_contracts as C
from src.ai.billing import verification_observations as V


class ConfirmationError(ValueError):
    """Safe database category only; never expose provider/consent payloads."""


class TrialConfirmationRepository:
    def __init__(self, connection, *, attestor=False):
        role = 'ceopro_trial_attestor' if attestor else 'ceopro_trial_confirmer'
        with connection.cursor() as cursor:
            cursor.execute('SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')
            if cursor.fetchone() != (role, role, False, False):
                raise ConfirmationError('restricted_confirmation_socket_required')
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
        raise ConfirmationError('confirmation_' + category)

    def attest(self, claim, observation, consent_id, *, checkout_completed_at,
               checkout_expires_at, attestation_id=None):
        C._observation_type(observation, C.ProviderVerificationObservation)
        if (type(observation.request) is not C.TrialObservationRequest
                or observation.outcome is not C.VerificationOutcome.VERIFIED
                or observation.provenance.source is not C.ObservationSource.AUTHORITATIVE_LOOKUP
                or observation.provenance.stored_observation_id is not None):
            raise ConfirmationError('authoritative_trial_evidence_required')
        # Reconstruct via the accepted deep-immutable contracts before encoding.
        evidence = V.evidence_document(observation)
        return self._call('SELECT public.billing_confirmation_attest(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (str(attestation_id or uuid.uuid4()), claim['operation_id'], claim['version'],
             claim['claim_token'], str(consent_id), Json(V.request_document(observation.request)),
             Json(evidence), observation.provenance.observed_at,
             C._observation_time(checkout_completed_at), C._observation_time(checkout_expires_at)))

    def confirm(self, attestation_id):
        return self._call('SELECT public.billing_confirmation_apply(%s)', (str(attestation_id),))

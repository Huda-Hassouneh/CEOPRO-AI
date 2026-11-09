"""Dormant collection adapter. Only an approved server factory may construct it.

The immutable policy catalog and B2B eligibility attestor are deliberately absent
from runtime. A DTO or request Boolean is neither policy approval nor provider proof.
"""
from dataclasses import dataclass
import hashlib
import uuid
from src.ai.billing import recurring_consent as R

MISSING_APPROVALS = ('agreement_text', 'agreement_revision', 'language_version',
    'operator_details', 'trial_start_rule', 'renewal_cancellation_disclosures',
    'refund_review_policy', 'retention_policy')


class CollectionBlocked(ValueError):
    pass


@dataclass(frozen=True)
class PolicyDocument:
    # Future catalog approval_reference must pin the entire immutable bundle,
    # including operator/refund versions, not just a mutable website URL.
    policy_id: uuid.UUID
    agreement_text: str
    operator_details_version: str
    refund_review_version: str
    registry: tuple  # sorted immutable (key, scalar) pairs from approved catalog
    trial_start_mode: str | None = None  # No default legal/business start rule.

    def values(self):
        if (type(self.registry) is not tuple or any(type(p) is not tuple or len(p)!=2
                or type(p[0]) is not str or type(p[1]) is not str for p in self.registry)
                or len({p[0] for p in self.registry})!=len(self.registry)):
            raise CollectionBlocked('immutable_policy_registry_required')
        values = dict(self.registry)
        required = ('agreement_reference','agreement_revision','language_tag','agreement_digest',
            'cancellation_reference','renewal_disclosure_reference','trial_start_rule_reference',
            'retention_policy_reference','approval_reference')
        if (type(self.policy_id) is not uuid.UUID or not self.agreement_text.strip()
                or not self.operator_details_version.strip() or not self.refund_review_version.strip()
                or any(not isinstance(values.get(k), str) or not values[k].strip() for k in required)
                or values['agreement_digest'] != 'sha256:'+hashlib.sha256(self.agreement_text.encode('utf-8')).hexdigest()):
            raise CollectionBlocked('policy_not_approved')
        return values


class ConsentCollection:
    def __init__(self, tenant_id, actor_id, reservations, consents, *, policies=None, business_eligibility=None):
        self.tenant, self.actor = tenant_id, actor_id
        self.reservations, self.consents = reservations, consents
        self.policies, self.business_eligibility = policies, business_eligibility

    def _owned(self, operation):
        row = self.reservations.load(operation)
        if (row is None or row['reservation']['attempt_id'] != str(operation)
                or row['reservation']['tenant_id'] != self.tenant
                or row['reservation']['started_by_user_id'] != self.actor
                or row['checkout']['tenant_id'] != self.tenant
                or row['checkout']['attempt_id'] != str(operation)
                or row['checkout']['gateway_binding_id'] != row['reservation']['binding_id']):
            raise CollectionBlocked('owned_operation_required')
        return row

    def _policy(self, row, language, policy_id=None):
        if self.policies is None:
            raise CollectionBlocked('policy_not_approved')
        if (row['reservation']['trial_duration_days'] != 14 or self.business_eligibility is None
                or self.business_eligibility(row) is not True):
            raise CollectionBlocked('business_eligibility_required')
        document = self.policies(row, language, policy_id)
        if type(document) is not PolicyDocument:
            raise CollectionBlocked('policy_not_approved')
        # This names the evidence rule; consent itself supplies no trial timestamp.
        if document.trial_start_mode != 'provider_confirmed_trial_start':
            raise CollectionBlocked('approved_trial_start_rule_required')
        values = document.values()
        if values['language_tag'] != language or (policy_id and str(document.policy_id) != str(policy_id)):
            raise CollectionBlocked('policy_version_conflict')
        return document, values

    @staticmethod
    def _registry(document, values, registry):
        if (registry['policy_id'] != str(document.policy_id) or registry['status'] != 'approved'
                or any(registry.get(key) != value for key, value in values.items())):
            raise CollectionBlocked('policy_version_conflict')

    def prepare(self, operation, language):
        row = self._owned(operation)
        try:
            document, values = self._policy(row, language)
        except CollectionBlocked as error:
            return dict(state='pending_policy', missing_approvals=list(MISSING_APPROVALS),
                blocker=str(error), agreement_text=None, policy_revision=None)
        return dict(state='prepared', missing_approvals=[], blocker=None,
            agreement_text=document.agreement_text, policy_revision=values['agreement_revision'])

    def present(self, operation, language):
        row = self._owned(operation)
        document, values = self._policy(row, language)
        identity = uuid.uuid5(operation, 'consent-presentation:'+str(document.policy_id))
        value = self.consents.present(operation, document.policy_id, presentation_id=identity).unpack()
        self._registry(document, values, value['policy'])
        if (value['presentation_id'] != str(identity) or value['status'] != 'presented' or value['actor_id'] != self.actor
                or value['tenant_id'] != self.tenant or value['attempt_id'] != str(operation)
                or value['binding_id'] != row['reservation']['binding_id']
                or value['approved_terms'] != row['reservation']['approved_terms']):
            raise CollectionBlocked('presentation_conflict')
        return dict(state='presented', presentation_id=value['presentation_id'], challenge=value['challenge'],
            agreement_text=document.agreement_text, policy_revision=values['agreement_revision'], expires_at=value['expires_at'])

    def accept(self, operation, language, presentation_id, challenge, checked):
        if checked is not True:
            raise CollectionBlocked('unchecked_consent')
        row = self._owned(operation)
        # Missing catalog blocks even the protected read; no Boolean bypass.
        if self.policies is None:
            raise CollectionBlocked('policy_not_approved')
        value = self.consents.read(operation, presentation_id).unpack()
        p = value['presentation']
        document, values = self._policy(row, language, p['policy_id'])
        self._registry(document, values, value['policy'])
        if (p['presentation_id'] != str(presentation_id) or value['invalidation'] is not None or p['approved_terms'] != row['reservation']['approved_terms']
                or p['actor_id'] != self.actor or p['tenant_id'] != self.tenant
                or p['attempt_id'] != str(operation) or p['binding_id'] != row['reservation']['binding_id']):
            raise CollectionBlocked('presentation_conflict')
        # A1 owns DB time, challenge consumption, expiry and stabilized authorization.
        result = self.consents.accept(R.PresentationIdentity(presentation_id, p['terms_digest']), challenge,
            acceptance_id=uuid.uuid5(presentation_id, 'authenticated-acceptance-v1')).unpack()
        return dict(state='accepted', acceptance_id=result['acceptance_id'], accepted_at=result['accepted_at'])

    def withdraw(self, operation, presentation_id):
        self._owned(operation)
        self.consents.read(operation, presentation_id)  # exact original operation/actor, no client rebinding
        result = self.consents.invalidate(presentation_id, R.ConsentState.WITHDRAWN).unpack()
        return dict(state='withdrawn', recorded_at=result['recorded_at'])

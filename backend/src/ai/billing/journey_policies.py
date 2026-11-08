"""Installation boundary for immutable owner-approved policy bundles.

No files, URLs or defaults are loaded. Installation authority must pin the entire
bundle digest out of band and install matching A1 registry rows separately. This
class checks integrity, not legal approval; production installs no catalog.
"""
import hashlib
import json
from src.ai.billing.authenticated_consent import PolicyDocument, CollectionBlocked


class ApprovedPolicyCatalog:
    def __init__(self, documents, *, pinned_bundle_digest):
        if not documents or any(type(d) is not PolicyDocument for d in documents):
            raise CollectionBlocked('approved_policy_bundle_required')
        snapshot = tuple(documents)
        encoded = json.dumps([dict(policy_id=str(d.policy_id), agreement_text=d.agreement_text,
            operator_details_version=d.operator_details_version, refund_review_version=d.refund_review_version,
            registry=dict(d.registry), trial_start_mode=d.trial_start_mode) for d in snapshot],
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        if 'sha256:'+hashlib.sha256(encoded).hexdigest() != pinned_bundle_digest:
            raise CollectionBlocked('policy_bundle_digest_conflict')
        for d in snapshot: d.values()
        self._documents = snapshot

    def __call__(self, row, language, policy_id=None):
        matches = [d for d in self._documents if d.values()['language_tag']==language
                   and (policy_id is None or str(d.policy_id)==str(policy_id))]
        if len(matches)!=1:
            raise CollectionBlocked('exact_approved_policy_version_required')
        return matches[0]

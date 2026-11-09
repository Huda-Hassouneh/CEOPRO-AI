"""Explicit local TEST/Sandbox wiring. No startup DB/provider calls or grants.

Only synthetic tenant/actor pairs authorized in the reviewed private configuration
may use this installer. No default-provider credentials, policies, SQL role changes
or attestor/confirmer are supplied. Legacy Stripe composition is untouched.
"""
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit, unquote
import uuid

from src.ai.billing import payment_contracts as C
from src.ai.billing.authenticated_consent import ConsentCollection, PolicyDocument
from src.ai.billing.journey_policies import ApprovedPolicyCatalog
from src.ai.billing.journey_webhooks import JourneyWebhookReconciler, BoundStripeJourneyWebhookDecoder
from src.ai.billing.paddle_gateway import (BoundPaddleTransport, PaddleWebhookDecoder, PaddleDurableCustomerGateway,
    PaddleJourneyGateway, PaddleVerificationGateway, unique_object)
from src.ai.billing.stripe_api import BoundCustomerTransport
from src.ai.billing.stripe_gateway import StripeDurableCustomerGateway
from src.ai.billing.stripe_journey import StripeJourneyGateway
from src.ai.billing.stripe_verification import BoundStripeReadTransport, StripeVerificationGateway, API_VERSIONS
from src.ai.billing.subscription_journey import SubscriptionJourney, DispatchRepository
from src.ai.billing.customer_operations import CustomerRepository
from src.ai.billing.recurring_consent import ConsentRepository
from src.ai.billing.trial_coordinator import ReservationRepository, _binding
from src.ai.billing.verification_observations import ObservationRepository


PASSWORDS={'ceopro_app':'APP_DB_PASSWORD','ceopro_billing_setup':'BILLING_SETUP_DB_PASSWORD',
    'ceopro_consent_service':'KEEL_SANDBOX_CONSENT_DB_PASSWORD',
    'ceopro_billing_observer':'KEEL_SANDBOX_OBSERVER_DB_PASSWORD',
    'ceopro_journey_router':'KEEL_SANDBOX_ROUTER_DB_PASSWORD'}


class SandboxConfigurationError(ValueError):
    def __init__(self):super().__init__('Local sandbox configuration incomplete or unsafe')


@dataclass(frozen=True,repr=False)
class Gateway:
    binding: C.GatewayBinding
    credential: str = field(repr=False)
    signing_secret: str = field(repr=False)
    api_version: str
    merchant_reviewed: bool
    checkout_origin: str | None
    replay_window_seconds: int
    return_urls: tuple


def local_database(env):
    from scripts.billing_verification import is_test_database_name
    u=urlsplit(env.get('DATABASE_URL',''))
    if (env.get('KEEL_DEV_ISOLATED')!='1' or env.get('SENTRY_ENVIRONMENT')!='development'
            or any(env.get(k,'').lower() not in ('','dev','development','test','testing') for k in ('APP_ENV','ENVIRONMENT'))
            or env.get('RENDER') or env.get('KUBERNETES_SERVICE_HOST')
            or u.scheme not in ('postgres','postgresql') or u.hostname not in ('127.0.0.1','localhost','::1')
            or not u.port or u.query or u.fragment or not is_test_database_name(unquote(u.path.lstrip('/')))):
        raise SandboxConfigurationError()
    return dict(host=u.hostname,port=u.port,dbname=unquote(u.path.lstrip('/')),connect_timeout=3,sslmode='disable',gssencmode='disable')


def _https(url):
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.fragment:raise SandboxConfigurationError()
    return url


class SandboxRuntime:
    def __init__(self,document,env):
        self.database=local_database(env)
        self.passwords={role:env.get(name,'') for role,name in PASSWORDS.items()}
        if not all(self.passwords.values()):raise SandboxConfigurationError()
        if document.get('environment')!='test' or not document.get('provider_operations_authorization'):raise SandboxConfigurationError()
        self.parties=frozenset((str(uuid.UUID(p['tenant_id'])),str(uuid.UUID(p['actor_id']))) for p in document['synthetic_businesses'])
        if not self.parties:raise SandboxConfigurationError()
        self.gateways={}
        for v in document['gateways']:
            provider=v['provider']
            if provider not in ('stripe','paddle') or provider in self.gateways:raise SandboxConfigurationError()
            b=C.GatewayBinding(provider,C.GatewayEnvironment.TEST,v['merchant_account_id'],v['binding_id'])
            prefix='STRIPE' if provider=='stripe' else 'PADDLE'
            credential=env.get('KEEL_SANDBOX_'+prefix+'_API_KEY','')
            secret=env.get('KEEL_SANDBOX_'+prefix+'_WEBHOOK_SECRET','')
            if not secret or not credential.startswith(('sk_test_','rk_test_') if provider=='stripe' else ('pdl_sdbx_apikey_',)):
                raise SandboxConfigurationError()
            version=v['api_version']
            if version not in (API_VERSIONS if provider=='stripe' else ('1',)):raise SandboxConfigurationError()
            urls=tuple(_https(url) for url in v['return_urls'])
            if len(urls)!=2:raise SandboxConfigurationError()
            origin=v.get('checkout_origin')
            if provider=='paddle':
                if origin is None or urlsplit(_https(origin)).path not in ('','/'):raise SandboxConfigurationError()
                if origin.endswith('/'):raise SandboxConfigurationError()
                if urls[0].split('/')[0:3]!=origin.split('/')[0:3] or urlsplit(urls[0]).path!='/billing/paddle-payment':
                    raise SandboxConfigurationError()
            replay=v.get('customer_replay_window_seconds',0)
            if type(replay) is not int or replay<0:raise SandboxConfigurationError()
            self.gateways[provider]=Gateway(b,credential,secret,version,v.get('merchant_reviewed') is True,origin,replay,urls)
        if not self.gateways or len({g.binding.binding_id for g in self.gateways.values()})!=len(self.gateways):raise SandboxConfigurationError()
        self.policies=None
        if document.get('policies'):
            docs=[PolicyDocument(uuid.UUID(v['policy_id']),v['agreement_text'],v['operator_details_version'],v['refund_review_version'],
                tuple(sorted(v['registry'].items())),v['trial_start_mode']) for v in document['policies']]
            self.policies=ApprovedPolicyCatalog(docs,pinned_bundle_digest=env.get('KEEL_SANDBOX_POLICY_BUNDLE_DIGEST',''))

    def socket(self,role,party=None):
        """Direct password identity only, no administrative fallback/SET ROLE."""
        import psycopg2
        from src.ai import db
        raw=psycopg2.connect(**self.database,user=role,password=self.passwords[role])
        try:
            with raw.cursor() as q:
                q.execute("SELECT session_user,current_user,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole,rolinherit,rolreplication,has_schema_privilege(current_user,'public','CREATE'),EXISTS(SELECT FROM pg_auth_members WHERE member=r.oid OR roleid=r.oid) FROM pg_roles r WHERE rolname=current_user")
                authority=q.fetchone()
                # ceopro_app's historical definition uses INHERIT. With zero
                # incoming/outgoing memberships it conveys no inherited role
                # authority. Dedicated billing identities still require NOINHERIT.
                inherit=authority[6] if authority and role=='ceopro_app' else False
                if authority!=(role,role,False,False,False,False,inherit,False,False,False):raise SandboxConfigurationError()
            raw.rollback()
            if role=='ceopro_journey_router':raw.set_session(readonly=True)
            return db._BillingSetupConnection(db._UnpooledOwner(),raw,*party) if party else raw
        except BaseException:raw.close();raise

    def gateway(self,binding):
        g=self.gateways.get(binding.provider)
        if g is None or g.binding!=binding:raise ValueError('Original installed binding required')
        return g

    @contextmanager
    def journey(self,ctx):
        party=(str(ctx.tenant_id),str(ctx.user_id))
        if party not in self.parties:raise ValueError('Authorized synthetic business required')
        with ExitStack() as stack:
            setup=stack.enter_context(closing(self.socket('ceopro_billing_setup',party)))
            consent=stack.enter_context(closing(self.socket('ceopro_consent_service',party)))
            observe=stack.enter_context(closing(self.socket('ceopro_billing_observer',party)))
            reservations=ReservationRepository(setup);observations=ObservationRepository(observe)
            collection=ConsentCollection(*party,reservations,ConsentRepository(consent),policies=self.policies,
                business_eligibility=lambda row:(row['reservation']['tenant_id'],row['reservation']['started_by_user_id']) in self.parties)
            transports={}
            def transport(binding):
                g=self.gateway(binding)
                if binding.binding_id not in transports:
                    t=(BoundCustomerTransport(binding,g.credential,api_version=g.api_version,replay_window_seconds=g.replay_window_seconds)
                       if binding.provider=='stripe' else BoundPaddleTransport(binding,g.credential))
                    transports[binding.binding_id]=t
                    if binding.provider=='paddle':stack.callback(t._client.close)
                return transports[binding.binding_id]
            def customer(binding):
                g=self.gateway(binding);t=transport(binding)
                return StripeDurableCustomerGateway(binding,t) if binding.provider=='stripe' else PaddleDurableCustomerGateway(binding,t,merchant_reviewed=g.merchant_reviewed)
            def checkout(binding):
                g=self.gateway(binding);t=transport(binding)
                return (StripeJourneyGateway(binding,t,provider_consent_reviewed=g.merchant_reviewed,cancellation_supported=g.merchant_reviewed)
                    if binding.provider=='stripe' else PaddleJourneyGateway(binding,t,merchant_reviewed=g.merchant_reviewed,
                        approved_checkout_origin=g.checkout_origin,checkout_page_ready=g.merchant_reviewed))
            def observer(binding,history):
                g=self.gateway(binding)
                return (StripeVerificationGateway(binding,BoundStripeReadTransport(binding,g.credential,api_version=g.api_version),_setup_source=history)
                    if binding.provider=='stripe' else PaddleVerificationGateway(binding,transport(binding)))
            def contact(row):
                # Contact is an ordinary authenticated app read; setup has no
                # users-table privilege and must never gain one as a workaround.
                with closing(self.socket('ceopro_app',party)) as app_connection:
                    with app_connection.cursor() as q:
                        q.execute('SELECT u.email,c.business_name FROM public.users u JOIN public.tenant_users tu ON tu.user_id=u.user_id JOIN public.companies c ON c.tenant_id=tu.tenant_id WHERE c.tenant_id=%s AND u.user_id=%s',party)
                        value=q.fetchone()
                    app_connection.commit()
                if value is None:raise ValueError('Authenticated business contact required')
                return value
            # No runtime attestor/confirmer credentials. Readiness/capability proof
            # and separately authorized confirmation remain closed launch gates.
            yield SubscriptionJourney(collection,DispatchRepository(consent),CustomerRepository(setup),customer,checkout,
                observations,observer,contact=contact,return_urls=lambda row:self.gateway(_binding(row)).return_urls)

    @contextmanager
    def resolve(self,event):
        if type(event) is not C.VerifiedPaymentEvent or event.binding is None or event.kind is C.PaymentEventKind.UNKNOWN:
            raise ValueError('Supported authenticated bound event required')
        self.gateway(event.binding)
        data=event.raw_evidence.get('data') or {};metadata=data.get('custom_data') or (data.get('object') or {}).get('metadata') or {}
        operation=metadata.get('keel_journey_operation')
        if operation is not None:operation=str(uuid.UUID(operation))
        customer=event.customer.opaque_id if event.customer else None
        checkout=event.checkout.opaque_id if event.checkout else (event.invoice.opaque_id if event.provider=='paddle' and event.invoice else None)
        subscription=event.subscription.opaque_id if event.subscription else None
        with closing(self.socket('ceopro_journey_router')) as conn:
            with conn.cursor() as q:
                q.execute("""SELECT DISTINCT r.attempt_id,r.tenant_id,r.started_by_user_id FROM public.billing_trial_checkouts r
                    JOIN public.billing_checkout_attempts a USING(attempt_id,tenant_id)
                    WHERE r.binding_id=%s AND (%s::uuid=r.attempt_id OR a.provider_session_id=%s
                    OR EXISTS(SELECT FROM public.billing_observation_operations o WHERE o.attempt_id=r.attempt_id AND o.binding_id=r.binding_id
                        AND (o.provider_subscription_id=%s OR EXISTS(SELECT FROM public.billing_verification_observations h WHERE h.operation_id=o.operation_id AND h.evidence->>'subscription'=%s))))
                    AND (%s::text IS NULL OR EXISTS(SELECT FROM public.billing_customer_operations c WHERE c.tenant_id=r.tenant_id AND c.binding_id=r.binding_id AND c.provider_customer_id=%s AND c.state='succeeded'))""",
                    (event.binding.binding_id,operation,checkout,subscription,subscription,customer,customer))
                rows=q.fetchall()
            conn.commit()
        if len(rows)!=1:raise ValueError('Unique original journey required')
        op,tenant,actor=rows[0]
        op=uuid.UUID(str(op))  # psycopg may return UUID columns as text.
        with self.journey(SimpleNamespace(tenant_id=str(tenant),user_id=str(actor))) as flow:
            row=flow.collection._owned(op)
            if _binding(row)!=event.binding:raise ValueError('Original persisted namespace required')
            d=flow.dispatches.command(op,'read')
            if not d:raise ValueError('Original dispatch required')
            snapshot=flow.collection.consents.read(op,uuid.UUID(d['presentation_id'])).unpack()
            if snapshot.get('acceptance') is None:raise ValueError('Original acceptance required')
            language=snapshot['policy']['language_tag']
            if d['provider_checkout_id'] is None and d['submitted_at']:
                # Resolve an ambiguous original submission by GET only before
                # webhook reconciliation. No second sender election or POST.
                flow._accepted(op,language)
                gateway=flow.checkout_gateway(event.binding)
                session=gateway.recover(d)
                if session is None:raise ValueError('Original Checkout recovery pending')
                gateway.validate(session,d)
                if checkout is not None and session.reference.opaque_id!=checkout:raise ValueError('Signed original Checkout required')
                flow.dispatches.command(op,'session',acceptance=d['acceptance_id'],
                    customer=d['customer_operation_id'],session=session.reference.opaque_id)
            yield flow,op,language


def install(app,env=None):
    """Startup is configuration-only. Disabled is a strict no-op."""
    env=os.environ if env is None else env
    if env.get('KEEL_SANDBOX_ACCEPTANCE_ENABLED','').lower()!='true':return None
    try:
        local_database(env)
        document=json.loads(Path(env['KEEL_SANDBOX_CONFIG']).read_text(encoding='utf-8'),object_pairs_hook=unique_object)
        runtime=SandboxRuntime(document,env)
        if getattr(app.state,'bound_journey_webhooks',None) or getattr(app.state,'subscription_journey_factory',None):raise SandboxConfigurationError()
        handler=JourneyWebhookReconciler(runtime.resolve)
        endpoints={provider:((BoundStripeJourneyWebhookDecoder(g.binding,g.signing_secret) if provider=='stripe' else PaddleWebhookDecoder(g.binding,g.signing_secret)),handler)
            for provider,g in runtime.gateways.items()}
        app.state.bound_journey_webhooks=endpoints
        app.state.subscription_journey_factory=runtime.journey
        return runtime
    except Exception:raise SandboxConfigurationError() from None

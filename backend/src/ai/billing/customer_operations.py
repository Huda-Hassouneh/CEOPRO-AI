"""Durable customer identity; no provider SDK, transport fields or trial policy."""
from datetime import datetime, timezone, timedelta
import json
import uuid

from src.ai.billing import checkout_attempts, store
from src.ai.billing.payment_contracts import (
    CustomerIntent, CustomerRecoveryIntent, FrozenCustomerRequest,
    PaymentProviderError, ProviderOperationOutcome, ProviderReference,
)


class CustomerOperationError(ValueError):
    pass


def active(conn, tenant_id, provider):
    with conn.cursor() as cur:
        cur.execute('SELECT operation_id,idempotency_key,request_params,replay_window_seconds,state,provider_customer_id,first_submitted_at,created_at '
                    "FROM billing_customer_operations WHERE tenant_id=%s AND provider=%s AND state<>'rejected'", (tenant_id,provider))
        row=cur.fetchone()
    return dict(zip(('operation_id','key','params','window','state','customer','submitted_at','created_at'),row)) if row else None


def _validate(snapshot, tenant_id, reference=None):
    if snapshot.deleted or snapshot.tenant_reference != str(tenant_id) or (reference and snapshot.reference != reference):
        raise CustomerOperationError('customer_identity_conflict')
    return snapshot.reference


def _confirm(conn, tenant_id, operation, snapshot):
    reference=_validate(snapshot,tenant_id)
    if reference.provider != operation['provider']:
        raise CustomerOperationError('customer_identity_conflict')
    store.save_customer(conn,tenant_id,reference.opaque_id)
    if operation['state']!='succeeded':
        with conn.cursor() as cur:
            cur.execute("UPDATE billing_customer_operations SET state='succeeded',provider_customer_id=%s,last_error=NULL,updated_at=clock_timestamp() WHERE operation_id=%s",
                        (reference.opaque_id,str(operation['operation_id'])))
    conn.commit()
    return reference.opaque_id


def resolve(conn, setup, tenant_id, email, company_name, gateway):
    # Shared with all Checkout paths, including Custom; reentrant on one socket.
    with checkout_attempts.tenant_lock(setup,tenant_id):
        mapped=store.customer_id(conn,tenant_id)
        if mapped:
            reference=ProviderReference(gateway.provider,mapped)
            _validate(gateway.get_customer(reference,tenant_reference=tenant_id),tenant_id,reference)
            return mapped
        operation=active(setup,tenant_id,gateway.provider)
        if not operation:
            identifier=str(uuid.uuid4())
            request=gateway.prepare_customer(CustomerIntent(tenant_id,email,company_name,identifier,'keel-customer-create-'+identifier))
            if request.provider!=gateway.provider or not 0<request.replay_window_seconds or request.idempotency_key!='keel-customer-create-'+identifier:
                raise CustomerOperationError('customer_identity_conflict')
            with setup.cursor() as cur:
                cur.execute('INSERT INTO billing_customer_operations(operation_id,tenant_id,provider,idempotency_key,request_params,replay_window_seconds) '
                            'VALUES(%s,%s,%s,%s,%s::jsonb,%s)', (identifier,tenant_id,request.provider,request.idempotency_key,json.dumps(request.payload),request.replay_window_seconds))
            setup.commit()
            operation=active(setup,tenant_id,gateway.provider)
        operation['provider']=gateway.provider
        if operation['state']=='succeeded':
            reference=ProviderReference(gateway.provider,operation['customer'])
            snapshot=gateway.get_customer(reference,tenant_reference=tenant_id)
            return _confirm(setup,tenant_id,operation,snapshot)
        request=FrozenCustomerRequest(gateway.provider,operation['key'],operation['params'],operation['window']) if operation['params'] is not None else None
        if operation['submitted_at'] or operation['state']=='legacy_unresolved':
            recovered=gateway.recover_customer(CustomerRecoveryIntent(tenant_id,str(operation['operation_id']),operation['key'],operation['created_at'],request))
            if recovered is not None:
                return _confirm(setup,tenant_id,operation,recovered)
            if request is None or datetime.now(timezone.utc)>=operation['submitted_at']+timedelta(seconds=operation['window']):
                raise CustomerOperationError('customer_creation_reconciling')
        with setup.cursor() as cur:
            cur.execute("UPDATE billing_customer_operations SET state='submitted',first_submitted_at=COALESCE(first_submitted_at,clock_timestamp()),updated_at=clock_timestamp() WHERE operation_id=%s",
                        (str(operation['operation_id']),))
        setup.commit()
        try:
            return _confirm(setup,tenant_id,operation,gateway.submit_customer(request))
        except Exception as error:
            setup.rollback()
            rejected=isinstance(error,PaymentProviderError) and error.outcome==ProviderOperationOutcome.REJECTED
            with setup.cursor() as cur:
                cur.execute("UPDATE billing_customer_operations SET state=%s,last_error=%s,updated_at=clock_timestamp() WHERE operation_id=%s AND state IN ('prepared','submitted','unknown')",
                            ('rejected' if rejected else 'unknown',error.outcome.value if isinstance(error,PaymentProviderError) else 'unconfirmed_result',str(operation['operation_id'])))
            setup.commit()
            raise

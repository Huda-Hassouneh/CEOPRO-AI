"""Real restricted SQL with synthetic Paddle Customer responses only."""
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import uuid
import psycopg2
import pytest
from src.ai import db
from src.ai.billing import customer_operations as U,payment_bindings
from src.ai.billing.paddle_gateway import PaddleDurableCustomerGateway
from src.ai.billing import payment_contracts as C
from .test_customer_operations_db import parties,restricted_runtime,fingerprint,expire
from .test_paddle_completion import CustomerReader

@pytest.fixture
def paddle(owner_db,parties):
    with owner_db.cursor() as q:
        q.execute('UPDATE billing_gateway_bindings SET reservation_enabled=false WHERE reservation_enabled')
        bid='paddle_'+uuid.uuid4().hex
        q.execute("INSERT INTO billing_gateway_bindings(binding_id,provider,environment,merchant_account_id,reservation_enabled,provenance) VALUES(%s,'paddle','test',%s,true,'SYNTHETIC acceptance fixture')",(bid,bid))
    with closing(db.billing_setup_connection(*parties[0])) as conn:b=payment_bindings.selected(conn)
    t=CustomerReader(b);g=PaddleDurableCustomerGateway(b,t,merchant_reviewed=True)
    intent=C.CustomerIntent(*[parties[0][0],str(uuid.uuid4()),'original',b,'synthetic@example.test','Synthetic business'])
    yield parties,intent,g,t


def resolve(p):
    parties,intent,g,t=p
    with closing(db.billing_setup_connection(*parties[0])) as c:return U.resolve(U.CustomerRepository(c),intent,lambda b:g)


def test_single_customer_send_recovers_lost_response_without_rights_or_resubmission(owner_db,paddle):
    parties,intent,g,t=paddle;before=fingerprint(owner_db);t.lost=True
    with pytest.raises(U.CustomerOperationError):resolve(paddle)
    found=resolve(paddle)
    assert resolve(paddle)==found and found.binding==intent.binding
    assert sum(v[0]=='POST' for v in t.calls)==1 and fingerprint(owner_db)==before
    with closing(db.billing_setup_connection(*parties[0])) as c:
        r=U.CustomerRepository(c).read(intent.operation_id)
        assert r['dispatch_count']==1 and r['replay_supported'] is False and r['replay_window_seconds']==0
    with closing(db.billing_setup_connection(*parties[1])) as c:
        assert U.CustomerRepository(c).read(intent.operation_id) is None


def test_paddle_second_sql_dispatch_and_forged_same_key_are_denied(owner_db,paddle):
    parties,intent,g,t=paddle
    with closing(db.billing_setup_connection(*parties[0])) as c:
        repo=U.CustomerRepository(c);r=repo.begin(intent,g.prepare_customer(intent));token=uuid.uuid4()
        r=repo.command(r,'claim',token);r=repo.command(r,'dispatch',token)
        with pytest.raises(psycopg2.Error) as error:repo.command(r,'dispatch',token)
        assert error.value.pgcode=='55000'
        assert repo.read(intent.operation_id)['dispatch_count']==1
    assert not t.calls


def test_concurrent_paddle_customer_has_one_sender(owner_db,paddle):
    before=fingerprint(owner_db)
    def attempt():
        try:return resolve(paddle)
        except (psycopg2.Error,U.CustomerOperationError):return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:attempt(),range(2)))
    assert any(results) and sum(v[0]=='POST' for v in paddle[3].calls)==1
    assert fingerprint(owner_db)==before


def test_revoked_paddle_billing_actor_cannot_dispatch(owner_db,paddle):
    parties,intent,g,t=paddle
    with owner_db.cursor() as q:q.execute("UPDATE tenant_users SET role_key='staff' WHERE tenant_id=%s AND user_id=%s",parties[0])
    with pytest.raises(psycopg2.Error) as error:resolve(paddle)
    assert error.value.pgcode=='42501' and not t.calls

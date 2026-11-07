"""RAG-specific execution fencing and message association.

Provider work is never retried after it may have started. Short transactions
own the preparation lease; the network call runs without a row lock.
"""
from datetime import datetime, timezone
import json
from uuid import uuid4

from fastapi import HTTPException


def prepare(conn, tenant_id, user_id, operation_ref):
    token = str(uuid4())
    with conn.cursor() as cur:
        cur.execute('INSERT INTO public.rag_logical_requests (tenant_id,user_id,operation_ref) '
                    'VALUES (%s,%s,%s) ON CONFLICT (tenant_id,operation_ref) DO NOTHING',
                    (tenant_id, user_id, operation_ref))
        cur.execute('SELECT state, session_id, user_message_id, assistant_message_id, lease_expires_at, conversation_state '
                    'FROM public.rag_logical_requests WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s FOR UPDATE',
                    (tenant_id, user_id, operation_ref))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(409, detail='Request is not available.')
        state, session, user_message, assistant, lease_until, conversation_state = row
        if state == 'completed':
            conn.commit()
            return {'completed': True, 'assistant': str(assistant), 'session': str(session)}
        if state == 'failed':
            conn.commit()
            raise HTTPException(409, detail={'code': 'request_failed'})
        if state == 'provider_started':
            conn.commit()
            raise HTTPException(409, detail={'code': 'request_pending_or_unknown'})
        if lease_until is not None and lease_until > datetime.now(timezone.utc):
            conn.commit()
            raise HTTPException(409, detail={'code': 'request_in_progress'})
        cur.execute("UPDATE public.rag_logical_requests SET lease_owner=%s, lease_expires_at=now()+interval '10 minutes' "
                    "WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s AND state='preparing'",
                    (token, tenant_id, user_id, operation_ref))
    conn.commit()
    return {'completed': False, 'lease': token, 'session': str(session) if session else None,
            'user_message': str(user_message) if user_message else None, 'conversation_state': conversation_state}


def fail_preparing(conn, tenant_id, user_id, operation_ref, lease):
    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_logical_requests SET state='failed',lease_owner=NULL,lease_expires_at=NULL "
                    "WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s AND state='preparing' "
                    "AND lease_owner=%s AND lease_expires_at>now() RETURNING operation_ref",
                    (tenant_id, user_id, operation_ref, lease))
        changed = cur.fetchone() is not None
    conn.commit()
    return changed


def bind_turn(conn, tenant_id, user_id, operation_ref, lease, session, message, conversation_state=None):
    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_logical_requests SET session_id=%s,user_message_id=%s,conversation_state=%s::jsonb "
                    "WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s AND state='preparing' "
                    "AND lease_owner=%s AND lease_expires_at>now() AND user_message_id IS NULL RETURNING operation_ref",
                    (session, message, json.dumps(conversation_state), tenant_id, user_id, operation_ref, lease))
        if cur.fetchone() is None:
            raise HTTPException(409, detail={'code': 'request_lease_lost'})


def begin_provider(conn, tenant_id, user_id, operation_ref, lease):
    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_logical_requests SET state='provider_started' "
                    "WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s AND state='preparing' "
                    "AND lease_owner=%s AND lease_expires_at>now() AND user_message_id IS NOT NULL RETURNING operation_ref",
                    (tenant_id, user_id, operation_ref, lease))
        if cur.fetchone() is None:
            raise HTTPException(409, detail={'code': 'request_lease_lost'})
    conn.commit()


def complete(conn, tenant_id, user_id, operation_ref, lease, message):
    with conn.cursor() as cur:
        cur.execute("UPDATE public.rag_logical_requests SET assistant_message_id=%s,state='completed', "
                    "lease_owner=NULL,lease_expires_at=NULL WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s "
                    "AND state='provider_started' AND lease_owner=%s RETURNING operation_ref",
                    (message, tenant_id, user_id, operation_ref, lease))
        if cur.fetchone() is None:
            raise HTTPException(409, detail={'code': 'request_lease_lost'})


def replay(conn, tenant_id, user_id, operation_ref):
    with conn.cursor() as cur:
        # Serialize with a possibly in-flight answer/association commit before
        # deciding that a result is missing after a lost commit acknowledgement.
        cur.execute('SELECT state FROM public.rag_logical_requests '
                    'WHERE tenant_id=%s AND user_id=%s AND operation_ref=%s FOR UPDATE',
                    (tenant_id, user_id, operation_ref))
        cur.fetchone()
        cur.execute("SELECT m.content,m.sources,m.answer_payload,m.session_id FROM public.rag_logical_requests r "
                    "JOIN public.conversation_messages m ON m.tenant_id=r.tenant_id AND m.user_id=r.user_id "
                    "AND m.session_id=r.session_id AND m.message_id=r.assistant_message_id "
                    "WHERE r.tenant_id=%s AND r.user_id=%s AND r.operation_ref=%s AND r.state='completed' "
                    "AND m.role='assistant' FOR UPDATE OF r", (tenant_id, user_id, operation_ref))
        row = cur.fetchone()
    if row is None:
        raise HTTPException(409, detail={'code': 'request_result_missing'})
    content, sources, payload, session = row
    return {**(payload or {}), 'answer': content, 'sources': sources, 'session_id': str(session)}

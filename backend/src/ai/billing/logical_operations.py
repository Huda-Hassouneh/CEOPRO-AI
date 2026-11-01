"""Tenant-scoped identity for metered work, separate from provider attempts.

Claiming an existing operation does not authorize a second execution. Callers
must inspect ``created`` and the status and implement their own retry policy.
"""
import hashlib
import json

from src.ai.billing import credits


class OperationConflict(ValueError):
    """An operation ID is already bound to different immutable input."""


def fingerprint(value) -> str:
    """Hash canonical JSON without persisting the customer's input."""
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError) as exc:
        raise ValueError('operation input must be finite JSON data') from exc
    return hashlib.sha256(encoded).hexdigest()


def claim(tenant_id: str, logical_operation_id: str, operation_kind: str,
          input_fingerprint: str, *, actor_user_id=None, conn_factory=None) -> dict:
    if not isinstance(logical_operation_id, str) or not 1 <= len(logical_operation_id) <= 200:
        raise ValueError('invalid logical operation ID')
    if not isinstance(operation_kind, str) or not 1 <= len(operation_kind) <= 80:
        raise ValueError('invalid operation kind')
    if (not isinstance(input_fingerprint, str) or len(input_fingerprint) != 64
            or any(c not in '0123456789abcdef' for c in input_fingerprint)):
        raise ValueError('invalid input fingerprint')
    conn = (conn_factory or (lambda: credits._scoped_connection(tenant_id, actor_user_id)))()
    try:
        with conn.cursor() as cur:
            cur.execute(
                'INSERT INTO public.billing_logical_operations '
                '(tenant_id, logical_operation_id, operation_kind, input_fingerprint, actor_user_id) '
                'VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id, logical_operation_id) DO NOTHING '
                'RETURNING id, status',
                (tenant_id, logical_operation_id, operation_kind, input_fingerprint, actor_user_id),
            )
            row = cur.fetchone()
            created = row is not None
            if not created:
                cur.execute('SELECT id, status, operation_kind, input_fingerprint, actor_user_id '
                            'FROM public.billing_logical_operations '
                            'WHERE tenant_id=%s AND logical_operation_id=%s',
                            (tenant_id, logical_operation_id))
                row = cur.fetchone()
                if row is None:
                    raise RuntimeError('logical operation is not visible')
                if (row[2] != operation_kind or row[3] != input_fingerprint
                        or (str(row[4]) if row[4] is not None else None) !=
                           (str(actor_user_id) if actor_user_id is not None else None)):
                    raise OperationConflict('logical operation ID already has different input')
        conn.commit()
        return {'id': str(row[0]), 'status': row[1], 'created': created}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish(tenant_id: str, operation_ref: str, status: str, *, conn_factory=None) -> None:
    if status not in ('succeeded', 'failed', 'unknown'):
        raise ValueError('invalid final operation status')
    conn = (conn_factory or (lambda: credits._scoped_connection(tenant_id)))()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE public.billing_logical_operations SET status=%s, updated_at=now() "
                        "WHERE tenant_id=%s AND id=%s AND status='in_progress' RETURNING id",
                        (status, tenant_id, operation_ref))
            if cur.fetchone() is None:
                raise OperationConflict('operation is missing or already terminal')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

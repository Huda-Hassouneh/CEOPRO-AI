"""Dormant restricted persistence. No provider selection is exposed to tenants.

Recording references is not provider verification. Phase 1.4 must establish
customer ownership before future runtime callers use this storage boundary.
"""
from src.ai.billing.payment_contracts import GatewayBinding, GatewayEnvironment, ProviderReference


def _setup(conn):
    if not getattr(conn, "billing_setup_only", False):
        raise ValueError("Restricted billing setup connection required")
    with conn.cursor() as cur:
        cur.execute("SELECT session_user,current_user,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        if cur.fetchone() != ("ceopro_billing_setup", "ceopro_billing_setup", False, False):
            raise ValueError("Password-authenticated restricted billing setup required")


def selected(conn):
    _setup(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_selected_gateway_binding()")
        row = cur.fetchone()[0]
    return GatewayBinding(row["provider"], GatewayEnvironment(row["environment"]),
                          row["merchant_account_id"], row["binding_id"])


def record_customer_reference(conn, reference: ProviderReference):
    _setup(conn)
    if reference.binding is None or reference.binding != selected(conn):
        raise ValueError("Explicit server-selected binding required")
    with conn.cursor() as cur:
        cur.execute("SELECT public.billing_record_customer_reference(%s,%s)",
                    (reference.binding.binding_id, reference.opaque_id))
        return cur.fetchone()[0]

"""
KEEL - RAG Business Copilot conversation persistence (Phase 2, Part 7).

Real DB-backed conversation history - closes the gap RAG_BUSINESS_COPILOT_
ARCHITECTURE.md already documented ("no conversation persistence table").
Backed by conversation_sessions/conversation_messages
(migrations/20260925030000_add_rag_conversation_persistence.sql), both
RLS-protected on tenant_id AND user_id (a conversation is one person's
chat, not shared company data) - every function here relies on the
connection's own RLS scoping (db.py::app_role_connection(), which sets
both app.current_tenant_id and app.current_user_id via SET LOCAL) rather
than trusting its own tenant_id/user_id arguments for security: a session
belonging to a different tenant or a different user within the same
tenant simply will not be visible to a SELECT/UPDATE/DELETE on this
connection, regardless of what caller passes in.

Bounded, not unbounded: load_session_history() caps how many prior
messages are returned, same MAX_HISTORY_MESSAGES bound llm_client.py's
own _sanitize_history() already enforces server-side - this module
enforces it at the query level too (LIMIT), not just after the fact.
"""
from typing import List, Optional

# Mirrors rag/llm_client.py's MAX_HISTORY_MESSAGES (12 = 6 user/assistant
# turns) - kept as a separate constant rather than importing that module,
# to avoid a circular import (llm_client already has enough of those -
# see its own lazy orchestrator import).
MAX_HISTORY_MESSAGES = 12

# A session list is a small sidebar/dropdown, not a paginated archive.
DEFAULT_SESSION_LIST_LIMIT = 20

_TITLE_MAX_LENGTH = 80


def _derive_title(first_message: str) -> str:
    text = (first_message or "").strip()
    if len(text) <= _TITLE_MAX_LENGTH:
        return text
    return text[:_TITLE_MAX_LENGTH].rstrip() + "..."


def create_session(conn, tenant_id: str, user_id: str, first_message: str) -> str:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO conversation_sessions (tenant_id, user_id, title) VALUES (%s, %s, %s) RETURNING session_id;",
            (tenant_id, user_id, _derive_title(first_message)),
        )
        return str(cursor.fetchone()[0])


def append_message(conn, tenant_id: str, session_id: str, user_id: str, role: str, content: str, sources: Optional[list] = None) -> str:
    import json

    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO conversation_messages (tenant_id, session_id, user_id, role, content, sources) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING message_id;",
            (tenant_id, session_id, user_id, role, content, json.dumps(sources) if sources is not None else None),
        )
        message_id = cursor.fetchone()[0]
        # updated_at drives list_sessions()'s "most recently active first"
        # ordering - RLS on conversation_sessions still applies to this
        # UPDATE (tenant_id/user_id-scoped), so this is a no-op (0 rows)
        # if session_id doesn't actually belong to this connection's tenant/user.
        cursor.execute(
            "UPDATE conversation_sessions SET updated_at = CURRENT_TIMESTAMP WHERE tenant_id = %s AND session_id = %s;",
            (tenant_id, session_id),
        )
        return str(message_id)


def session_exists(conn, tenant_id: str, session_id: str) -> bool:
    """False both when the session genuinely doesn't exist AND when it
    belongs to a different tenant/user (RLS makes those indistinguishable
    at the SQL level, which is exactly the correct security behavior - a
    caller should get the same "not found" either way, never a hint that
    a session id is valid but belongs to someone else)."""
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM conversation_sessions WHERE tenant_id = %s AND session_id = %s;", (tenant_id, session_id))
        return cursor.fetchone() is not None


def load_session_history(conn, tenant_id: str, session_id: str, limit: int = MAX_HISTORY_MESSAGES) -> List[dict]:
    """Returns [{"role": ..., "content": ...}, ...] oldest-first - the
    exact shape rag/llm_client.py::answer_query()'s own `history` param
    already expects, so this can be passed straight through unchanged."""
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT role, content FROM (
                SELECT role, content, seq FROM conversation_messages
                WHERE tenant_id = %s AND session_id = %s
                ORDER BY seq DESC
                LIMIT %s
            ) recent ORDER BY seq ASC;
            """,
            (tenant_id, session_id, limit),
        )
        return [{"role": role, "content": content} for role, content in cursor.fetchall()]


def load_session_messages_for_display(conn, tenant_id: str, session_id: str) -> List[dict]:
    """Full message list (role/content/sources/created_at) for a page-
    refresh restore - unbounded within one session (a real chat, not a
    massive archive; no evidence this needs pagination yet)."""
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT message_id, role, content, sources, created_at FROM conversation_messages "
            "WHERE tenant_id = %s AND session_id = %s ORDER BY seq ASC;",
            (tenant_id, session_id),
        )
        rows = cursor.fetchall()
    return [
        {
            "message_id": str(message_id),
            "role": role,
            "content": content,
            "sources": sources or [],
            "created_at": created_at.isoformat(),
        }
        for message_id, role, content, sources, created_at in rows
    ]


def list_sessions(conn, tenant_id: str, user_id: str, limit: int = DEFAULT_SESSION_LIST_LIMIT) -> List[dict]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT session_id, title, created_at, updated_at FROM conversation_sessions "
            "WHERE tenant_id = %s AND user_id = %s ORDER BY updated_at DESC LIMIT %s;",
            (tenant_id, user_id, limit),
        )
        rows = cursor.fetchall()
    return [
        {"session_id": str(session_id), "title": title, "created_at": created_at.isoformat(), "updated_at": updated_at.isoformat()}
        for session_id, title, created_at, updated_at in rows
    ]

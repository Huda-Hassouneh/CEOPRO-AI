"""
KEEL - Database Source Adapter.
Reads a result set from any DB-API 2.0 compatible connection into the
(headers, rows) shape the pipeline expects. The caller supplies the SQL.
"""
from typing import Dict, List, Optional, Tuple


def read_db_query(
    conn, query: str, params: Optional[tuple] = None, max_rows: Optional[int] = None
) -> Tuple[List[str], List[Dict[str, object]]]:
    """`max_rows` stops a query that returns far more than expected from filling memory:
    more rows than that is an error, never a silently shortened result."""
    with conn.cursor() as cursor:
        cursor.execute(query, params or ())
        headers = [col[0] for col in cursor.description]
        records = cursor.fetchall() if max_rows is None else cursor.fetchmany(max_rows + 1)
        if max_rows is not None and len(records) > max_rows:
            raise ValueError(f"The query returned more than {max_rows} rows. Narrow it and try again.")
        rows = [dict(zip(headers, record)) for record in records]
    return headers, rows

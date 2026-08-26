"""
CEOPRO AI - Database Source Adapter.
Reads a result set from any DB-API 2.0 compatible connection into the
(headers, rows) shape the pipeline expects. The caller supplies the SQL.
"""
from typing import Dict, List, Optional, Tuple


def read_db_query(
    conn, query: str, params: Optional[tuple] = None
) -> Tuple[List[str], List[Dict[str, object]]]:
    with conn.cursor() as cursor:
        cursor.execute(query, params or ())
        headers = [col[0] for col in cursor.description]
        rows = [dict(zip(headers, record)) for record in cursor.fetchall()]
    return headers, rows

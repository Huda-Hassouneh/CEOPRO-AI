"""
In-memory stand-in for the psycopg2 connection CEOPRO-AI pipelines take as `conn`.

The pipeline, data_access and evidence modules run UNMODIFIED: their SELECTs are
answered from the request's own input rows (via per-service `routes`), and their
INSERT ... RETURNING statements are captured and returned to the caller as the
records that would have been persisted. Any SQL this responder doesn't
recognise raises instead of silently returning nothing.
"""
import re
import uuid


class UnsupportedQuery(RuntimeError):
    pass


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.description = None
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def connection(self):
        return self._conn

    def mogrify(self, template, args):
        # psycopg2.extras.execute_values() builds multi-row VALUES via mogrify; keep each
        # row's real values and emit a placeholder token that execute() maps back.
        self._conn._mogrified.append(tuple(args))
        return f"\x00{len(self._conn._mogrified) - 1}\x00".encode()

    def execute(self, query, params=None):
        if isinstance(query, bytes):
            query = query.decode("utf-8")
            tokens = [int(t) for t in re.findall(r"\x00(\d+)\x00", query)]
            if tokens:
                q = " ".join(re.sub(r"\x00\d+\x00", "", query).split())
                m = re.match(r"(?i)^INSERT INTO (\w+)\s*\(([^)]*)\)", q)
                names = [c.strip() for c in m.group(2).split(",")]
                ids = []
                for t in tokens:
                    row = self._conn._mogrified[t]
                    record = {"table": m.group(1), "id": str(uuid.uuid4())}
                    record.update({n: (v.isoformat() if hasattr(v, "isoformat") else v) for n, v in zip(names, row)})
                    self._conn.persisted.append(record)
                    ids.append((record["id"],))
                self.rowcount = len(tokens)
                if re.search(r"(?i)\bRETURNING\b", q):
                    self._rows, self.description = ids, [("id",)]
                else:
                    self._rows, self.description = [], None
                return
        q = " ".join(query.split())
        params = tuple(params or ())
        self.description, self.rowcount = None, -1
        if re.match(r"(?i)^(SAVEPOINT|RELEASE SAVEPOINT|ROLLBACK TO SAVEPOINT)\b", q):
            self._rows = []
            return
        m = re.match(r"(?i)^(UPDATE|DELETE FROM) (\w+)", q)
        if m:
            self._conn.persisted.append({"table": m.group(2), "op": m.group(1).split()[0].upper(), "params": [
                v.isoformat() if hasattr(v, "isoformat") else v for v in params]})
            self._rows, self.rowcount = [], 1
            if re.search(r"(?i)\bRETURNING\b", q):
                self._rows, self.description = [(str(uuid.uuid4()),)], [("id",)]
            return
        m = re.match(r"(?i)^INSERT INTO (\w+)", q)
        if m:
            new_id = str(uuid.uuid4())
            cols = re.search(r"\(([^)]*)\)\s*VALUES", q)
            names = [c.strip() for c in cols.group(1).split(",")] if cols else []
            record = {"table": m.group(1), "id": new_id}
            record.update({n: (v.isoformat() if hasattr(v, "isoformat") else v) for n, v in zip(names, params)})
            self._conn.persisted.append(record)
            self._rows, self.description, self.rowcount = [(new_id,)], [("id",)], 1
            return
        for pattern, handler in self._conn.routes:
            if re.search(pattern, q, re.I | re.S):
                self._rows = list(handler(q, params))
                self.description, self.rowcount = [("col",)], len(self._rows)
                return
        raise UnsupportedQuery(f"No in-memory data source for query: {q[:160]}")

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = self._rows, []
        return rows

    def close(self):
        pass


class MemConn:
    def __init__(self, routes):
        self.routes = routes  # list of (regex, handler(query, params) -> rows)
        self.persisted = []
        self._mogrified = []
        self.encoding = "UTF8"

    def cursor(self, *a, **k):
        return _Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass

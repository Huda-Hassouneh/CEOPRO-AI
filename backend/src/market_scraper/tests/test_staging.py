from src.market_scraper.staging import content_hash, resolve_stage, stage_record


class Cursor:
    def __init__(self):
        self.calls = []
        self.row = ("stage-1",)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params):
        self.calls.append((" ".join(query.split()), params))

    def fetchone(self):
        return self.row


class Connection:
    def __init__(self):
        self.cursor_instance = Cursor()
        self.commits = 0

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        self.commits += 1


def item(**updates):
    base = {
        "tenant_id": "tenant-1", "source_id": "source-1", "job_id": "job-1",
        "mapping_id": "mapping-1", "product_name": "Trail Shoe", "price_amount": 10,
        "currency": "USD", "product_url": "https://shop.example/trail-shoe",
        "safety_flags": [],
    }
    return {**base, **updates}


def test_stage_is_idempotent_per_job_mapping_and_content():
    connection = Connection()
    assert stage_record(connection, item()) == "stage-1"
    query, params = connection.cursor_instance.calls[0]
    assert "ON CONFLICT" in query
    assert params[5] == content_hash(item())
    assert connection.commits == 1


def test_terminal_stage_status_is_explicit():
    connection = Connection()
    resolve_stage(connection, "tenant-1", "stage-1", "REJECTED", ("bad price",))
    query, params = connection.cursor_instance.calls[0]
    assert "validation_status" in query
    assert params[0] == "REJECTED"

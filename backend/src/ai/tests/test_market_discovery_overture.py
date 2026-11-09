"""Overture Maps places as a discovery source: which places count as
competitors, their names and links, and the parts of the dataset read.
Rows below have the shape of the real dataset's rows."""
import json

import pytest

from src.market_scraper.market_discovery import industries, pipeline
from src.market_scraper.market_discovery.models import DiscoveryQuery
from src.market_scraper.market_discovery.providers import osm, overture


def _query(industry="pharmacy", **overrides):
    ind = industries.get(industry)
    values = dict(tenant_id="t", industry_key=ind.key, industry_label=ind.label_en, keywords=["صيدلية", "pharmacy"],
                  latitude=24.7136, longitude=46.6753, radius_km=10, city="Riyadh", country_code="SA",
                  osm_tags=ind.osm_tags, google_types=ind.google_types)
    values.update(overrides)
    return DiscoveryQuery(**values)


def _row(name, category, datasets, socials=None, websites=None, record="123"):
    return {"id": "08f-" + name, "names": {"primary": name, "common": None}, "basic_category": category,
            "taxonomy": {"primary": category, "hierarchy": [category], "alternates": None},
            "websites": websites, "socials": socials, "phones": ["+966 11 000 0000"],
            "addresses": [{"freeform": "King Fahd Rd", "locality": "Riyadh", "country": "SA"}],
            "sources": [{"dataset": d, "record_id": record} for d in datasets] + [{"dataset": "Overture", "record_id": None}],
            "confidence": 0.8, "operating_status": "open",
            "bbox": {"xmin": 46.68, "xmax": 46.68, "ymin": 24.72, "ymax": 24.72}}


def test_a_category_counts_only_from_a_reliable_contributor_or_with_the_name_agreeing():
    assert overture._category_trusted(_row("Nahdi", "pharmacy", ["meta"]))
    assert not overture._category_trusted(_row("كنتاكي", "pharmacy", ["Microsoft"]))  # KFC filed as a pharmacy
    assert overture._category_trusted(_row("Boots", "pharmacy", ["Microsoft", "Foursquare"]))


def test_match_words_come_from_the_query_not_from_any_fixed_list():
    assert "pharmacy" in overture.match_words(_query()) and "chemist" in overture.match_phrases(_query())
    restaurant = _query("restaurant", keywords=["restaurant"])
    assert overture.category_matches(_row("Reem", "fast_food_restaurant", ["meta"]), overture.match_words(restaurant), overture.match_phrases(restaurant))
    assert not overture.category_matches(_row("Club", "tennis_court", ["meta"]), overture.match_words(restaurant), overture.match_phrases(restaurant))
    custom = _query("restaurant", industry_key="custom", industry_label="Software company", keywords=["Software company"],
                    osm_tags=(), google_types=())
    assert overture.match_words(custom) == {"software"}  # "company" says nothing


def test_a_place_becomes_a_candidate_with_its_names_and_a_link_to_where_it_came_from():
    q = _query()
    meta = overture.to_candidate(_row("صيدلية ليمون", "pharmacy", ["meta"], socials=["https://www.facebook.com/1234"]), q, True, True)
    assert (meta.name, meta.name_ar, meta.source_url, meta.industry_key) == ("صيدلية ليمون", "صيدلية ليمون", "https://www.facebook.com/1234", "pharmacy")
    venue = overture.to_candidate(_row("Boots", "pharmacy", ["Foursquare"], record="4be3", websites=["boots.com.sa"]), q, True, False)
    assert venue.source_url == "https://foursquare.com/v/4be3" and venue.website == "https://boots.com.sa"
    assert overture.to_candidate(_row("Whites", "pharmacy", ["AllThePlaces"], websites=["https://www.whites.net/ar/"]), q, True, False).source_url == "https://www.whites.net/ar/"


def test_only_the_parts_of_the_dataset_around_the_company_are_read():
    class Stat:
        def __init__(self, low, high):
            self.min, self.max = low, high

    class Column:
        def __init__(self, path, stat):
            self.path_in_schema, self.path, self.statistics = path, path, stat

    class RowGroup:
        def __init__(self, x, y):
            self.cols = [Column("bbox.xmin", Stat(x, x + 1)), Column("bbox.xmax", Stat(x, x + 1)),
                         Column("bbox.ymin", Stat(y, y + 1)), Column("bbox.ymax", Stat(y, y + 1))]

        def column(self, i):
            return self.cols[i]

    class Meta:
        def __init__(self, groups):
            self.groups, self.num_row_groups, self.num_columns = groups, len(groups), 4
            self.schema = self

        def column(self, i):
            return self.groups[0].cols[i]

        def row_group(self, i):
            return self.groups[i]

    meta = Meta([RowGroup(46.2, 24.3), RowGroup(35.5, 31.5), RowGroup(-74, 40)])
    index = {"files": [["a.parquet", 1]], "groups": overture._compact_groups(0, meta)}
    assert overture._row_groups(index, overture._box(_query())) == [("a.parquet", 1, 0)]


def test_a_business_type_described_in_arabic_matches_names_by_word_stem():
    import re
    pattern = re.compile(osm._name_pattern(["مكتب عقاري"], by_word=True))
    assert pattern.search("مكتب الدوحة للعقارات") and pattern.search("شركة العقارية المتحدة")
    assert not pattern.search("مكتب محاماة")  # "office" alone is not the trade


def test_arabic_only_descriptions_get_english_category_words_once():
    asked = []
    query = pipeline.build_query("t", {"business_type": "مكتب عقاري", "city": "Doha", "country_code": "QA",
                                       "latitude": 25.2854, "longitude": 51.531})
    pipeline._CATEGORY_WORDS_CACHE.clear()

    def ask(messages, **kwargs):
        asked.append(messages[-1]["content"])
        return '["real estate agent", "property management"]'

    enriched = pipeline.with_category_words(query, ask=ask)
    assert set(enriched.category_words) == {"estate", "property"}  # not "real", "agent", "management"
    assert "real estate agent" in enriched.keywords and "مكتب عقاري" in enriched.keywords
    pipeline.with_category_words(query, ask=ask)
    assert len(asked) == 1  # cached
    english = pipeline.build_query("t", {"business_type": "Software company", "latitude": 1, "longitude": 1})
    assert pipeline.with_category_words(english, ask=ask) is english  # English already: nothing asked


def test_rows_outside_the_search_or_closed_or_unsure_are_dropped_before_python_reads_them():
    import pyarrow as pa

    def row(x, y, status="open", confidence=0.8):
        return {"bbox": {"xmin": x, "xmax": x, "ymin": y, "ymax": y}, "operating_status": status, "confidence": confidence}

    rows = [row(46.68, 24.72), row(46.68, 24.72, status=None), row(46.68, 24.72, status=""),
            row(46.68, 24.72, status="permanently_closed"), row(46.68, 24.72, confidence=0.1),
            row(46.68, 24.72, confidence=None), row(10.0, 24.72), row(None, None), row(0.0, 24.72)]
    kept = overture._in_box(pa.Table.from_pylist(rows), overture._box(_query())).to_pylist()
    assert [(r["operating_status"], r["confidence"]) for r in kept] == [("open", 0.8), (None, 0.8), ("", 0.8)]


def test_a_small_api_container_never_reads_overture_itself(monkeypatch):
    from src.ai.core import ml_runtime

    monkeypatch.delenv("OVERTURE_EXECUTION", raising=False)
    monkeypatch.delenv("OFFLOAD_PROCESSOR_URL", raising=False)
    monkeypatch.setattr(ml_runtime, "container_memory_limit_mb", lambda: 512)
    monkeypatch.setattr(overture, "search_local", lambda q: (_ for _ in ()).throw(AssertionError("read locally")))
    result = overture.search(_query())
    assert (result.status, result.reason) == ("skipped", "needs_processor")


@pytest.mark.parametrize("limit_mb", [None, 512, 16384, 1 << 20])
def test_the_api_never_reads_overture_itself_whatever_memory_it_reports(monkeypatch, limit_mb):
    """1-1.7 GB of Overture in the API process ran the 512 MB production API out of memory. The decision
    must not depend on reading the host's memory limit: unreadable, small or huge, the API delegates."""
    from src.ai.core import ml_runtime

    monkeypatch.delenv("OVERTURE_EXECUTION", raising=False)
    monkeypatch.delenv("OFFLOAD_PROCESSOR_URL", raising=False)
    monkeypatch.setattr(ml_runtime, "container_memory_limit_mb", lambda: limit_mb)
    monkeypatch.setattr(overture, "search_local", lambda q: (_ for _ in ()).throw(AssertionError("read in the API")))
    assert overture.execution_mode() == "unsafe"
    result = overture.search(_query())
    assert (result.status, result.reason) == ("skipped", "needs_processor")


@pytest.mark.parametrize("setting", ["auto", "AUTO ", "", "something-else"])
def test_only_an_explicit_local_setting_reads_overture_in_process(monkeypatch, setting):
    from src.market_scraper.market_discovery.models import ProviderResult

    monkeypatch.delenv("OFFLOAD_PROCESSOR_URL", raising=False)
    monkeypatch.setenv("OVERTURE_EXECUTION", setting)
    assert overture.execution_mode() == "unsafe"
    monkeypatch.setenv("OVERTURE_EXECUTION", "local")  # the processor image, or a development machine on purpose
    monkeypatch.setattr(overture, "search_local", lambda q: ProviderResult("overture", "ok"))
    assert overture.execution_mode() == "local" and overture.search(_query()).status == "ok"


def test_with_a_processor_configured_auto_delegates_to_it(monkeypatch):
    from src.offload import client as offload

    monkeypatch.delenv("OVERTURE_EXECUTION", raising=False)
    monkeypatch.setattr(offload, "configured", lambda: True)
    assert overture.execution_mode() == "remote"


def test_with_a_processor_configured_overture_runs_there_and_returns_the_same_candidates(monkeypatch):
    from src.offload import client as offload

    calls = []

    class FakeClient:
        def run(self, kind, params, deadline_seconds):
            calls.append((kind, params))
            row = _row("Nahdi", "pharmacy", ["meta"], socials=["https://facebook.com/nahdi"])
            candidate = overture.to_candidate(row, _query(), True, False)
            from dataclasses import asdict
            return {"status": "ok", "reason": None, "requests": 3, "candidates": [asdict(candidate)]}

    monkeypatch.setenv("OVERTURE_EXECUTION", "remote")
    monkeypatch.setattr(offload, "get_client", lambda: FakeClient())
    result = overture.search(_query())
    assert result.status == "ok" and result.requests == 3
    assert [c.name for c in result.candidates] == ["Nahdi"] and result.candidates[0].source_url == "https://facebook.com/nahdi"
    assert calls[0][0] == "overture.search" and "tenant_id" not in calls[0][1]


def test_an_unavailable_processor_fails_only_the_overture_source(monkeypatch):
    from src.offload import client as offload

    class DownClient:
        def run(self, kind, params, deadline_seconds):
            raise offload.OffloadUnavailable("circuit_open")

    monkeypatch.setenv("OVERTURE_EXECUTION", "remote")
    monkeypatch.setattr(offload, "get_client", lambda: DownClient())
    result = overture.search(_query())
    assert (result.status, result.reason, result.candidates) == ("failed", "processor_unavailable", [])


# --- The in-process reader is memory-bounded (measured on real data 8 Nov 2026: Dubai 15 km 1,002 MB -> 279 MB,
#     identical candidates). These tests pin the properties that made that true. --------------------------------

def _fake_dataset(monkeypatch, parts, fail=()):
    """search_local over `parts` (each a list of rows) with no network: a fake ParquetFile streams each part."""
    import threading
    import pyarrow as pa
    import pyarrow.parquet as pq

    state = {"active": 0, "peak": 0, "whole_group_reads": 0, "batch_sizes": []}
    lock = threading.Lock()

    class FakeFile:
        def __init__(self, source, pre_buffer=True):
            self.part = int(source.url.rsplit("/", 1)[-1])
            assert pre_buffer is False, "a whole row group must not be buffered up front"

        def read_row_group(self, *args, **kwargs):
            state["whole_group_reads"] += 1
            raise AssertionError("decoding a whole row group is what ran the API out of memory")

        def iter_batches(self, batch_size, row_groups, columns, use_threads=True):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            try:
                if self.part in fail:
                    raise OSError("part unreachable")
                rows = parts[self.part]
                for start in range(0, len(rows), batch_size):
                    state["batch_sizes"].append(len(rows[start:start + batch_size]))
                    yield pa.RecordBatch.from_pylist(rows[start:start + batch_size]).select(columns)
            finally:
                with lock:
                    state["active"] -= 1

    class FakeRange:
        def __init__(self, url, client, size=None):
            self.url = url

    monkeypatch.setattr(pq, "ParquetFile", FakeFile)
    monkeypatch.setattr(overture, "_RangeFile", FakeRange)
    monkeypatch.setattr(overture, "available", lambda: (True, None))
    monkeypatch.setattr(overture, "_client", lambda: None)
    monkeypatch.setattr(overture, "_load_index", lambda client: {})
    monkeypatch.setattr(overture, "_row_groups", lambda index, box: [(str(i), 1, 0) for i in range(len(parts))])
    return state


def _old_full_row_result(rows, query):
    """What the previous reader returned for the same rows (every in-box row turned into a full dict)."""
    wanted, phrases = overture.match_words(query), overture.match_phrases(query)
    pattern = overture._name_pattern(query.keywords, by_word=query.industry_key == industries.CUSTOM)
    import re
    name_re = re.compile(pattern, re.IGNORECASE) if pattern else None
    box, radius = overture._box(query), min(query.radius_km, overture.MAX_RADIUS_KM)
    return sorted(c.source_ref for _d, c in overture._candidates(rows, query, wanted, phrases, name_re, box, radius))


def _mixed_rows(prefix, n):
    rows = []
    for i in range(n):
        if i % 3 == 0:
            rows.append(_row(f"{prefix} Pharmacy {i}", "pharmacy", ["meta"], record=f"{prefix}{i}", socials=[f"https://facebook.com/{prefix}{i}"]))
        elif i % 3 == 1:
            rows.append(_row(f"{prefix} Burger {i}", "fast_food_restaurant", ["meta"], record=f"{prefix}{i}", socials=[f"https://facebook.com/{prefix}{i}"]))
        else:
            rows.append(_row(f"صيدلية {prefix}{i}", "pharmacy", ["Microsoft"], record=f"{prefix}{i}", socials=[f"https://facebook.com/{prefix}{i}"]))  # name agrees
    return rows


@pytest.mark.parametrize("workers", [1, 2, 3])
def test_reads_stream_in_batches_with_a_bounded_number_in_flight(monkeypatch, workers):
    parts = [_mixed_rows(f"p{n}", 25) for n in range(8)]
    state = _fake_dataset(monkeypatch, parts)
    monkeypatch.setattr(overture, "READ_WORKERS", workers)
    monkeypatch.setattr(overture, "READ_BATCH_ROWS", 10)
    result = overture.search_local(_query())
    assert result.status == "ok"
    assert state["whole_group_reads"] == 0
    assert 1 <= state["peak"] <= workers
    assert max(state["batch_sizes"]) <= 10


def test_bounded_reading_returns_exactly_what_full_rows_returned(monkeypatch):
    parts = [_mixed_rows(f"p{n}", 30) for n in range(5)]
    _fake_dataset(monkeypatch, parts)
    monkeypatch.setattr(overture, "READ_BATCH_ROWS", 7)
    query = _query()
    got = sorted(c.source_ref for c in overture.search_local(query).candidates)
    assert got and got == _old_full_row_result([row for part in parts for row in part], query)


def test_one_unreachable_part_leaves_the_others_and_all_failing_is_reported(monkeypatch):
    parts = [_mixed_rows(f"p{n}", 9) for n in range(4)]
    _fake_dataset(monkeypatch, parts, fail={1})
    result = overture.search_local(_query())
    assert result.status == "ok" and result.candidates
    assert not any(c.source_ref.startswith("p1") for c in result.candidates)
    _fake_dataset(monkeypatch, parts, fail={0, 1, 2, 3})
    assert (overture.search_local(_query()).status, overture.search_local(_query()).reason) == ("failed", "unreachable")


# --- Compact mirror (cell packs): what the API reads in production --------------------------------------------
# Measured 9 Nov 2026 on real data (release 2026-10-21.0): Amman 5 km 0.8 s / +16 MB, Dubai 15 km 2.2 s / +25 MB,
# identical candidates to reading Overture directly; pyarrow never loaded in the API process.

def _pack_fixture(tmp_path, rows):
    import pyarrow as pa
    from scripts.overture_mirror import build

    stem = "cell_40_20"
    index = build.write_pack(pa.Table.from_pylist(rows), str(tmp_path / f"{stem}.pack"))
    files = {
        "cells.json": json.dumps({"format": 1, "cells": {stem: {"places": len(rows)}}}).encode(),
        f"{stem}.idx.json": json.dumps({"format": 1, "tiles": index}).encode(),
        f"{stem}.pack": (tmp_path / f"{stem}.pack").read_bytes(),
    }
    return files, index


def _serve(monkeypatch, files, calls=None, fail=()):
    import httpx

    def handler(request):
        name = request.url.path.rsplit("/", 1)[-1]
        if calls is not None:
            calls.append(name)
        if name in fail:
            return httpx.Response(503)
        if name not in files:
            return httpx.Response(404)
        body = files[name]
        rng = request.headers.get("Range")
        if rng:
            start, end = (int(v) for v in rng.split("=")[1].split("-"))
            return httpx.Response(206, content=body[start:end + 1])
        return httpx.Response(200, content=body)

    monkeypatch.setattr(overture, "MIRROR_URL", "https://mirror.test/r")
    monkeypatch.setattr(overture, "_mirror_cache", {})
    monkeypatch.setattr(overture, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.delenv("OVERTURE_EXECUTION", raising=False)


def _mirror_rows():
    rows = _mixed_rows("m", 30)
    for i, row in enumerate(rows):
        row["bbox"] = {"xmin": 46.68 + i * 0.0001, "xmax": 46.68 + i * 0.0001, "ymin": 24.72, "ymax": 24.72}
    return rows


def test_the_mirror_is_the_default_when_configured_and_returns_what_full_rows_return(monkeypatch, tmp_path):
    import sys
    rows = _mirror_rows()
    files, _ = _pack_fixture(tmp_path, rows)
    _serve(monkeypatch, files)
    assert overture.execution_mode() == "mirror"
    query = _query()
    result = overture.search(query)
    assert result.status == "ok"
    got = sorted(c.source_ref for c in result.candidates)
    assert got and got == _old_full_row_result([overture_compact(r) for r in rows], query)


def overture_compact(row):
    from scripts.overture_mirror import build
    return json.loads(json.dumps(build.compact_place(row)))


def test_a_name_with_a_unicode_line_separator_stays_one_place(monkeypatch, tmp_path):
    rows = _mirror_rows()
    rows[0]["names"] = {"primary": "Nahdi Pharmacy\x85Branch", "common": None}
    files, _ = _pack_fixture(tmp_path, rows)
    _serve(monkeypatch, files)
    result = overture.search(_query())
    assert result.status == "ok"
    assert any(c.source_ref == rows[0]["id"] for c in result.candidates)


def test_a_damaged_place_is_skipped_not_the_search(monkeypatch, tmp_path):
    import gzip
    rows = _mirror_rows()
    files, index = _pack_fixture(tmp_path, rows)
    key, entry = next(iter(index.items()))
    offset, length, _n = entry[:3]
    text = gzip.decompress(files["cell_40_20.pack"][offset:offset + length]).decode()
    damaged = gzip.compress(("{not json\n" + text).encode(), mtime=0)
    files["cell_40_20.pack"] = damaged
    files["cell_40_20.idx.json"] = json.dumps({"format": 1, "tiles": {key: [0, len(damaged), _n + 1]}}).encode()
    _serve(monkeypatch, files)
    result = overture.search(_query())
    assert result.status == "ok" and result.candidates


def test_the_mirror_failing_is_reported_and_never_raises(monkeypatch, tmp_path):
    files, _ = _pack_fixture(tmp_path, _mirror_rows())
    _serve(monkeypatch, files, fail={"cells.json"})
    assert (overture.search(_query()).status, overture.search(_query()).reason) == ("failed", "unreachable")
    _serve(monkeypatch, files, fail={"cell_40_20.pack"})
    assert (overture.search(_query()).status, overture.search(_query()).reason) == ("failed", "unreachable")


def test_a_cell_without_places_is_an_empty_result_not_a_failure(monkeypatch, tmp_path):
    files, _ = _pack_fixture(tmp_path, _mirror_rows())
    files["cells.json"] = json.dumps({"format": 1, "covered": ["cell_40_20"], "cells": {}}).encode()
    calls = []
    _serve(monkeypatch, files, calls)
    result = overture.search(_query())
    assert (result.status, result.candidates) == ("ok", [])
    assert "cell_40_20.pack" not in calls


def test_a_region_the_mirror_has_not_built_says_not_covered_never_empty(monkeypatch, tmp_path):
    files, _ = _pack_fixture(tmp_path, _mirror_rows())
    files["cells.json"] = json.dumps({"format": 1, "covered": ["cell_30_30"], "cells": {"cell_30_30": {}}}).encode()
    _serve(monkeypatch, files)
    result = overture.search(_query())
    assert (result.status, result.reason, result.candidates) == ("skipped", "not_covered", [])


def test_oversized_tiles_and_huge_boxes_are_refused_without_reading(monkeypatch, tmp_path):
    files, _ = _pack_fixture(tmp_path, _mirror_rows())
    calls = []
    _serve(monkeypatch, files, calls)
    monkeypatch.setattr(overture, "MIRROR_MAX_TILE_BYTES", 10)
    assert overture.search(_query()).reason == "unreachable"
    assert "cell_40_20.pack" not in calls
    monkeypatch.setattr(overture, "MIRROR_MAX_TILES", 3)
    assert overture.search(_query()).reason == "too_large"


def test_reading_the_mirror_never_loads_pyarrow():
    import subprocess
    import sys
    code = ("import sys; from src.market_scraper.market_discovery.providers import overture; "
            "overture.search_mirror; print('pyarrow' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_cell_and_tile_lookup_covers_the_box_and_crosses_cell_edges():
    tiles = overture._mirror_tiles((49.95, 50.05, 19.95, 20.05))
    assert {stem for stem, _ in tiles} == {"cell_40_10", "cell_50_10", "cell_40_20", "cell_50_20"}
    assert len(tiles) == 4


def test_the_builder_keeps_only_what_discovery_reads_and_the_verifier_catches_damage(tmp_path):
    import pyarrow as pa
    from scripts.overture_mirror import build, verify

    rows = _mirror_rows()
    rows[0]["addresses"] = [{"freeform": "King Fahd Rd", "locality": "Riyadh", "country": "SA", "postcode": "12345"}]
    place = build.compact_place(rows[0])
    assert set(place) <= {"id", "names", "basic_category", "taxonomy", "bbox", "addresses", "websites", "socials",
                          "phones", "sources", "confidence", "operating_status"}
    assert place["addresses"] == [{"freeform": "King Fahd Rd", "locality": "Riyadh", "country": "SA"}]
    assert build.tile_key(46.68, 24.72) == "247:466" and build.tile_key(-0.05, -0.05) == "-1:-1"

    release = tmp_path / "2026-10-21.0"
    release.mkdir()
    index = build.write_pack(pa.Table.from_pylist(rows), str(release / "cell_40_20.pack"))
    (release / "cell_40_20.idx.json").write_text(json.dumps({"format": 1, "tiles": index}))
    (release / "cells.json").write_text(json.dumps({"format": 2, "covered": ["cell_40_20"],
                                                    "cells": {"cell_40_20": {"places": len(rows)}}}))
    assert verify.verify(str(release)) == []
    (release / "cells.json").write_text(json.dumps({"format": 2, "covered": ["cell_40_20"],
                                                    "cells": {"cell_40_20": {"places": len(rows) + 1}}}))
    assert any("places" in p for p in verify.verify(str(release)))
    data = bytearray((release / "cell_40_20.pack").read_bytes())
    data[len(data) // 2] ^= 0xFF
    (release / "cell_40_20.pack").write_bytes(bytes(data))
    assert any("sha256 mismatch" in p for p in verify.verify(str(release)))  # caught before decompressing


# --- Guards against a hostile or damaged tile (review finding 9 Nov 2026: a 398 KB tile inflated to +867 MB) ---

def _one_tile_mirror(monkeypatch, tmp_path, member: bytes, with_hash=True, entry=None):
    import hashlib
    files, _ = _pack_fixture(tmp_path, _mirror_rows())
    key = overture._mirror_tiles(overture._box(_query()))[0][1]
    files["cell_40_20.pack"] = member
    tile = entry if entry is not None else [0, len(member), 1] + ([hashlib.sha256(member).hexdigest()] if with_hash else [])
    files["cell_40_20.idx.json"] = json.dumps({"format": 2, "tiles": {key: tile}}).encode()
    _serve(monkeypatch, files)


def test_a_tile_that_inflates_past_the_limit_is_refused(monkeypatch, tmp_path):
    import gzip
    bomb = gzip.compress(b'{"id":"x","bbox":{}}\n' * 300_000, mtime=0)  # ~6 MB inflated from a few KB
    monkeypatch.setattr(overture, "MIRROR_MAX_TILE_INFLATED_BYTES", 1024 * 1024)
    _one_tile_mirror(monkeypatch, tmp_path, bomb)
    result = overture.search(_query())
    assert (result.status, result.reason) == ("failed", "unreachable")  # the only tile was refused


def test_an_over_long_line_is_one_damaged_place_and_the_rest_still_count(monkeypatch, tmp_path):
    import gzip
    from scripts.overture_mirror import build
    good = [json.dumps(build.compact_place(r)) for r in _mirror_rows()]
    member = gzip.compress(("\n".join(good[:5] + ["x" * 200_000] + good[5:]) + "\n").encode(), mtime=0)
    monkeypatch.setattr(overture, "MIRROR_MAX_LINE_BYTES", 64 * 1024)
    _one_tile_mirror(monkeypatch, tmp_path, member)
    result = overture.search(_query())
    assert result.status == "ok" and len(result.candidates) >= 10


def test_a_tile_whose_hash_does_not_match_is_refused(monkeypatch, tmp_path):
    import gzip
    member = gzip.compress(b"{}\n", mtime=0)
    _one_tile_mirror(monkeypatch, tmp_path, member, entry=[0, len(member), 1, "0" * 64])
    assert overture.search(_query()).reason == "unreachable"


@pytest.mark.parametrize("entry", ["not-a-list", [None, 3], ["a", "b", 1], [0, -5, 1], {"offset": 0}])
def test_a_malformed_index_entry_costs_that_tile_never_the_search(monkeypatch, tmp_path, entry):
    import gzip
    _one_tile_mirror(monkeypatch, tmp_path, gzip.compress(b"{}\n", mtime=0), entry=entry)
    result = overture.search(_query())
    assert (result.status, result.reason) == ("failed", "unreachable")  # reported, nothing raised


def test_keeping_only_the_nearest_matches_a_stable_sort_by_distance(monkeypatch, tmp_path):
    rows = _mirror_rows()
    files, _ = _pack_fixture(tmp_path, rows)
    _serve(monkeypatch, files)
    full = [c.source_ref for c in overture.search(_query()).candidates]
    monkeypatch.setattr(overture, "MAX_CANDIDATES", 4)
    monkeypatch.setattr(overture, "_mirror_cache", {})
    assert [c.source_ref for c in overture.search(_query()).candidates] == full[:4]


def test_an_inflation_bomb_cannot_grow_the_process_memory():
    """The review's probe, as a test: a tile of a few hundred KB that inflates to ~400 MB, read by the real
    reader in a separate process with the default limits. Peak memory growth must stay small."""
    import subprocess
    import sys
    code = r'''
import gzip, json, resource, sys
from src.market_scraper.market_discovery.providers import overture
bomb = gzip.compress(b'{"id":"x","bbox":{"xmin":0,"ymin":0}}\n' * 10_000_000, mtime=0)
long_line = gzip.compress(b"y" * 400_000_000, mtime=0)
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
outcomes = []
for member in (bomb, long_line):
    try:
        outcomes.append(sum(1 for _ in overture._tile_lines(member)))
    except overture._TileTooLarge:
        outcomes.append("refused")
grown_mb = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - before) / 1024
print(json.dumps({"compressed_kb": [len(bomb) // 1024, len(long_line) // 1024], "outcomes": outcomes, "grown_mb": grown_mb}))
'''
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=300)
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["outcomes"][0] == "refused"          # inflated past 96 MB -> refused
    assert result["outcomes"][1] == "refused"          # 400 MB in one "line" also inflates past the cap
    assert result["grown_mb"] < 40, result             # without the guards this grew by hundreds of MB

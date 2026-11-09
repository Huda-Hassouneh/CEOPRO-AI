"""
Builds the compact Overture Places mirror that competitor discovery reads.

Overture's release stores ~20,000 places per row group across wide areas, so a city search decodes many
places it can't use (a 15 km Dubai search peaked near 1 GB). This writes, per 10 x 10 degree cell, only the
columns discovery reads and only open, confident places, sorted by location into small row groups. The API
then range-reads just the few small groups covering a search (see providers/overture.py, mirror mode).

  python -m scripts.overture_mirror.build --out-dir /tmp/mirror --packs-dir /tmp/packs --cells-file config/overture_mirror_cells.json
  python -m scripts.overture_mirror.build --out-dir /tmp/mirror --packs-dir /tmp/packs --cells="-20,10 30,30"

Runs where memory is plentiful (a CI runner), never in the API. Output: <release>/cell_<lon>_<lat>.parquet
plus index.json ([file, group, xmin, xmax, ymin, ymax] per row group, the same shape the provider uses).
"""
import argparse
import gzip
import hashlib
import json
import logging
import math
import os
import sys
import time

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.market_scraper.market_discovery.providers import overture

logger = logging.getLogger("OVERTURE_MIRROR")
CELL_DEGREES = 10
ROW_GROUP_ROWS = int(os.getenv("OVERTURE_MIRROR_ROW_GROUP_ROWS", "2000"))
SORT_BIN_DEGREES = 0.05  # rows sorted by ~5 km latitude bands, then longitude: each small group covers a compact area


def all_cells():
    return [(lon, lat) for lon in range(-180, 180, CELL_DEGREES) for lat in range(-90, 90, CELL_DEGREES)]


def build_cell(index: dict, lon: int, lat: int) -> pa.Table:
    box = (lon, lon + CELL_DEGREES, lat, lat + CELL_DEGREES)
    parts = []
    for key, size, group in overture._row_groups(index, box):
        reader = pq.ParquetFile(overture._RangeFile(overture.BASE_URL + key, overture._client(), size), pre_buffer=False)
        for batch in reader.iter_batches(batch_size=8192, row_groups=[group], columns=overture.COLUMNS, use_threads=False):
            kept = overture._in_box(batch, box)
            # Keep each place in exactly one cell (its south-west corner inside it).
            xmin, ymin = pc.struct_field(kept.column("bbox"), "xmin"), pc.struct_field(kept.column("bbox"), "ymin")
            own = pc.and_(pc.and_(pc.greater_equal(xmin, box[0]), pc.less(xmin, box[1])),
                          pc.and_(pc.greater_equal(ymin, box[2]), pc.less(ymin, box[3])))
            kept = kept.filter(pc.fill_null(own, False))
            if kept.num_rows:
                parts.append(pa.Table.from_batches([kept]))
    if not parts:
        return None
    table = pa.concat_tables(parts, promote_options="permissive")
    bbox = table.column("bbox")
    band = pc.floor(pc.divide(pc.struct_field(bbox, "ymin"), SORT_BIN_DEGREES))
    table = table.append_column("_band", band).append_column("_x", pc.struct_field(bbox, "xmin"))
    table = table.sort_by([("_band", "ascending"), ("_x", "ascending")]).drop_columns(["_band", "_x"])
    return table


def write_cell(table: pa.Table, path: str) -> int:
    pq.write_table(table, path, row_group_size=ROW_GROUP_ROWS, compression="zstd", write_statistics=True)
    return os.path.getsize(path)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--cells", help='space-separated "lon,lat" of each cell\'s south-west corner, e.g. --cells="-20,10 30,30"')
    parser.add_argument("--cells-file", help="JSON file with {\"cells\": [\"lon,lat\", ...]} (backend/config/overture_mirror_cells.json)")
    parser.add_argument("--packs-dir", help="also write the cell packs the API reads into this folder")
    args = parser.parse_args()
    client = overture._client()
    index = overture._load_index(client)
    release = index["release"]
    out = os.path.join(args.out_dir, release)
    os.makedirs(out, exist_ok=True)
    if args.cells:
        names = args.cells.split()
    elif args.cells_file:
        names = json.load(open(args.cells_file))["cells"]
    else:
        names = None
    cells = [tuple(int(v) for v in c.split(",")) for c in names] if names else all_cells()
    files, groups = [], []
    for lon, lat in cells:
        started = time.monotonic()
        table = build_cell(index, lon, lat)
        if table is None:
            continue
        name = f"cell_{lon}_{lat}.parquet"
        size = write_cell(table, os.path.join(out, name))
        meta = pq.ParquetFile(os.path.join(out, name)).metadata
        number = len(files)
        files.append([name, size])
        groups.extend(overture._compact_groups(number, meta))
        logger.info("cell %s,%s: %d places, %.1f MB, %d row groups, %.0f s", lon, lat, table.num_rows, size / 2**20,
                    meta.num_row_groups, time.monotonic() - started)
    covered = [f"cell_{lon}_{lat}" for lon, lat in cells]
    with open(os.path.join(out, "index.json"), "w") as handle:
        json.dump({"release": release, "source": "overture", "files": files, "groups": groups, "covered": covered}, handle)
    logger.info("mirror %s: %d files, %.1f MB total", release, len(files), sum(s for _n, s in files) / 2**20)
    if args.packs_dir:
        packs_from_parquet(out, os.path.join(args.packs_dir, release))
    return 0


if __name__ == "__main__":
    sys.exit(main())


# --- Cell packs: what the API actually reads -----------------------------------------------------------------
# One file per 10-degree cell made of independent gzip members, one per 0.1-degree tile (~11 km), each holding
# one JSON object per place with only the fields discovery reads. A per-cell index gives each tile's byte
# range, so the API range-reads the few tiles a search covers and streams them with the standard library:
# no pyarrow in the API, memory bounded by one tile.
TILE_DEGREES = 0.1
PACK_FORMAT = 2  # 2: tile entries carry a sha256


def tile_key(lon: float, lat: float) -> str:
    return f"{math.floor(lat / TILE_DEGREES)}:{math.floor(lon / TILE_DEGREES)}"


def compact_place(row: dict) -> dict:
    names = row.get("names") or {}
    common = names.get("common") or []
    common = dict(common) if isinstance(common, list) else dict(common)
    taxonomy = row.get("taxonomy") or {}
    address = ((row.get("addresses") or [None])[0]) or {}
    box = row.get("bbox") or {}
    place = {
        "id": row["id"],
        "names": {"primary": names.get("primary"),
                  "common": [[k, v] for k, v in common.items() if k in ("en", "ar") and v]},
        "basic_category": row.get("basic_category"),
        "taxonomy": {"primary": taxonomy.get("primary"), "alternates": list(taxonomy.get("alternates") or [])},
        "bbox": {k: box.get(k) for k in ("xmin", "xmax", "ymin", "ymax")},
        "addresses": [{k: address.get(k) for k in ("freeform", "locality", "country") if address.get(k)}],
        "websites": [w for w in (row.get("websites") or []) if isinstance(w, str)][:3],
        "socials": [s for s in (row.get("socials") or []) if isinstance(s, str)][:5],
        "phones": [p for p in (row.get("phones") or []) if p][:1],
        "sources": [{"dataset": s.get("dataset"), "record_id": s.get("record_id")} for s in (row.get("sources") or [])],
        "confidence": row.get("confidence"),
        "operating_status": row.get("operating_status"),
    }
    return {k: v for k, v in place.items() if v not in (None, [], {})} | {"id": row["id"], "bbox": place["bbox"]}


def write_pack(table, pack_path: str) -> dict:
    """Writes the cell pack; returns {tile: [offset, length, places]}."""
    tiles = {}
    for batch in table.to_batches(max_chunksize=20000):
        for row in batch.to_pylist():
            box = row.get("bbox") or {}
            if box.get("xmin") is None or box.get("ymin") is None:
                continue
            tiles.setdefault(tile_key(box["xmin"], box["ymin"]), []).append(
                json.dumps(compact_place(row), ensure_ascii=False, separators=(",", ":")))
    index, offset = {}, 0
    with open(pack_path, "wb") as handle:
        for key in sorted(tiles):
            member = gzip.compress(("\n".join(tiles[key]) + "\n").encode("utf-8"), compresslevel=9, mtime=0)
            handle.write(member)
            # [offset, length, places, sha256]: the API checks the hash, so a replaced asset is refused.
            index[key] = [offset, len(member), len(tiles[key]), hashlib.sha256(member).hexdigest()]
            offset += len(member)
    return index


def packs_from_parquet(parquet_dir: str, out_dir: str, covered=None) -> None:
    """Turns built cell_<lon>_<lat>.parquet files into cell packs plus cells.json. `covered` lists every cell
    the build looked at (including empty ones), so a search can tell "no places here" from "not built"."""
    os.makedirs(out_dir, exist_ok=True)
    cells = {}
    built = json.load(open(os.path.join(parquet_dir, "index.json")))
    release = built["release"]
    covered = sorted(set(covered or built.get("covered") or []))
    for name in sorted(os.listdir(parquet_dir)):
        if not (name.startswith("cell_") and name.endswith(".parquet")):
            continue
        stem = name[:-len(".parquet")]
        index = write_pack(pq.read_table(os.path.join(parquet_dir, name)), os.path.join(out_dir, stem + ".pack"))
        with open(os.path.join(out_dir, stem + ".idx.json"), "w") as handle:
            json.dump({"format": PACK_FORMAT, "tile_degrees": TILE_DEGREES, "tiles": index}, handle, separators=(",", ":"))
        cells[stem] = {"places": sum(v[2] for v in index.values()), "bytes": os.path.getsize(os.path.join(out_dir, stem + ".pack"))}
        logger.info("pack %s: %d tiles, %d places, %.1f MB", stem, len(index), cells[stem]["places"], cells[stem]["bytes"] / 2**20)
    with open(os.path.join(out_dir, "cells.json"), "w") as handle:
        json.dump({"format": PACK_FORMAT, "release": release, "source": "Overture Maps Foundation places",
                   "license": "CDLA-Permissive-2.0", "cell_degrees": CELL_DEGREES, "tile_degrees": TILE_DEGREES,
                   "covered": covered, "cells": cells}, handle, separators=(",", ":"))

"""
Checks built cell packs before they are published (the workflow refuses to publish on any problem):
cells.json shape, every cell's index and pack present, every tile decompresses, every line is one place with an
id and a bbox inside its tile, tile counts match, and no tile exceeds what the API agrees to read.

  python -m scripts.overture_mirror.verify <packs dir containing one <release>/ folder>
"""
import gzip
import json
import math
import os
import sys

from scripts.overture_mirror.build import CELL_DEGREES, PACK_FORMAT, TILE_DEGREES

MAX_TILE_BYTES = int(os.getenv("OVERTURE_MIRROR_MAX_TILE_BYTES", str(8 * 1024 * 1024)))


def verify(release_dir: str) -> list:
    problems = []
    cells = json.load(open(os.path.join(release_dir, "cells.json")))
    if cells.get("format") != PACK_FORMAT or not isinstance(cells.get("cells"), dict) or not isinstance(cells.get("covered"), list):
        return ["cells.json: wrong format or missing cells/covered"]
    if set(cells["cells"]) - set(cells["covered"]):
        problems.append("cells.json: a built cell is not listed as covered")
    total = 0
    for stem, info in cells["cells"].items():
        index_path, pack_path = (os.path.join(release_dir, f"{stem}{ext}") for ext in (".idx.json", ".pack"))
        if not (os.path.isfile(index_path) and os.path.isfile(pack_path)):
            problems.append(f"{stem}: index or pack missing")
            continue
        index = json.load(open(index_path))
        size = os.path.getsize(pack_path)
        lon0, lat0 = (int(v) for v in stem.split("_")[1:3])
        places = 0
        with open(pack_path, "rb") as pack:
            for key, (offset, length, count) in index["tiles"].items():
                if length > MAX_TILE_BYTES or offset + length > size:
                    problems.append(f"{stem} {key}: bad range or tile over {MAX_TILE_BYTES} bytes")
                    continue
                pack.seek(offset)
                lines = gzip.decompress(pack.read(length)).decode("utf-8").split("\n")
                rows = [json.loads(line) for line in lines if line]
                ty, tx = (int(v) for v in key.split(":"))
                for row in rows:
                    box = row.get("bbox") or {}
                    if not row.get("id") or box.get("xmin") is None or \
                            f"{math.floor(box['ymin'] / TILE_DEGREES)}:{math.floor(box['xmin'] / TILE_DEGREES)}" != key:
                        problems.append(f"{stem} {key}: a place without id/bbox or outside its tile")
                        break
                if len(rows) != count:
                    problems.append(f"{stem} {key}: {len(rows)} places, index says {count}")
                if not (lon0 <= tx * TILE_DEGREES + 1e-9 < lon0 + CELL_DEGREES and lat0 <= ty * TILE_DEGREES + 1e-9 < lat0 + CELL_DEGREES):
                    problems.append(f"{stem} {key}: tile outside its cell")
                places += len(rows)
        if places != info.get("places"):
            problems.append(f"{stem}: {places} places, cells.json says {info.get('places')}")
        total += places
    print(f"verified {len(cells['cells'])} cells, {total} places, {len(problems)} problem(s)")
    return problems


def main():
    root = sys.argv[1]
    releases = [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]
    if len(releases) != 1:
        print(f"expected exactly one release folder in {root}, found {releases}")
        return 1
    problems = verify(os.path.join(root, releases[0]))
    for problem in problems[:50]:
        print("PROBLEM:", problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

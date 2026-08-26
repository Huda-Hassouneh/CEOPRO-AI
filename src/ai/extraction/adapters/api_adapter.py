"""
CEOPRO AI - API / POS / ERP Source Adapter.
Normalizes a list of JSON records (single response or paginated) into
the same (headers, rows) shape every other adapter produces. `fetch_page`
is supplied by the caller and performs the actual call for one page - a
per-vendor integration only needs to implement fetch_page against that
vendor's API; the rest of the pipeline is unchanged regardless of vendor.
"""
from typing import Callable, Dict, List, Optional, Tuple


def flatten_records(
    records: List[Dict[str, object]]
) -> Tuple[List[str], List[Dict[str, object]]]:
    headers: List[str] = []
    seen = set()
    for record in records:
        for key in record.keys():
            if key not in seen:
                seen.add(key)
                headers.append(key)
    return headers, list(records)


def read_paginated_api(
    fetch_page: Callable[[int], Optional[List[Dict[str, object]]]],
    max_pages: int = 1000,
) -> Tuple[List[str], List[Dict[str, object]]]:
    all_records: List[Dict[str, object]] = []
    page = 1
    while page <= max_pages:
        records = fetch_page(page)
        if not records:
            break
        all_records.extend(records)
        page += 1
    return flatten_records(all_records)

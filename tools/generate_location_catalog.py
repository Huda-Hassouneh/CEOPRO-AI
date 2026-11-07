"""Rebuild the offline location snapshot without installing/executing upstream code.

Download: python -m pip download --no-deps --only-binary=:all: geonamescache==3.0.0 --dest .dev/location-catalog
Run: python tools/generate_location_catalog.py .dev/location-catalog/geonamescache-3.0.0-py3-none-any.whl
GeoNames data: CC BY 4.0, https://www.geonames.org/about.html
Package: https://github.com/yaph/geonamescache (MIT).
"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

WHEEL_SHA256 = "a6bed16ccd0bcfe6a822541ef8fb3192fe40e14905c2cdef1f51a13232585329"
ROOT = Path(__file__).resolve().parents[1]


def generate(wheel):
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != WHEEL_SHA256:
        raise ValueError("Unexpected wheel: review the source/version before updating the pinned digest")
    target = ROOT / "frontend/src/shared/config/locations"
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        countries = json.loads(archive.read("geonamescache/data/countries.json"))
        # Exclude retired AN/CS and user-assigned XK: current ISO alpha-2 set.
        codes = sorted(set(countries) - {"AN", "CS", "XK"})
        cities = json.loads(archive.read("geonamescache/data/cities500.json"))
    by_country = {code: set() for code in codes}
    for city in cities.values():
        name = city["name"].strip()
        if city["countrycode"] in by_country and 0 < len(name) <= 100:
            by_country[city["countrycode"]].add(name)
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    write(target / "country-codes.json", codes)
    for code, names in by_country.items():
        write(target / f"{code}.json", sorted(names))
    print(f"Generated {len(codes)} countries; {sum(map(len, by_country.values()))} city names")


if __name__ == "__main__":
    generate(Path(sys.argv[1]))

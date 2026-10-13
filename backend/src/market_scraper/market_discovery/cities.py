"""Built-in city centres for the markets KEEL serves, so a company that
gave its city (in English or Arabic, e.g. "Amman", "عمّان",
"Amman - Khalda") gets a search location immediately, with no geocoding
service involved. Online geocoders (geocode.py) are only asked for cities
not listed here.

The point is a city's centre, used as the middle of the search radius -
precise enough for "competitors in Amman", never shown as the company's
own address. Coordinates are public-domain city-centre values.
"""
import re
import unicodedata
from typing import Optional, Tuple

# (country, (latitude, longitude), names...)
_CITIES = [
    ("JO", (31.9539, 35.9106), "amman", "عمان", "عمّان"),
    ("JO", (32.0728, 36.0880), "zarqa", "az zarqa", "al zarqa", "الزرقاء", "الزرقا"),
    ("JO", (32.5556, 35.8500), "irbid", "اربد", "إربد"),
    ("JO", (29.5321, 35.0063), "aqaba", "العقبة", "العقبه"),
    ("JO", (32.0392, 35.7272), "salt", "as salt", "al salt", "السلط"),
    ("JO", (31.7167, 35.8000), "madaba", "مادبا", "مأدبا"),
    ("JO", (32.2747, 35.8961), "jerash", "جرش"),
    ("JO", (32.3434, 36.2080), "mafraq", "al mafraq", "المفرق"),
    ("JO", (31.1853, 35.7047), "karak", "al karak", "kerak", "الكرك"),
    ("JO", (32.3326, 35.7517), "ajloun", "عجلون"),
    ("JO", (30.1962, 35.7341), "maan", "ma'an", "معان"),
    ("JO", (30.8375, 35.6042), "tafilah", "tafila", "الطفيلة"),
    ("JO", (32.0469, 35.8853), "sweileh", "صويلح"),
    ("JO", (31.9930, 35.8550), "wadi al seer", "وادي السير"),
    ("JO", (32.1000, 36.0300), "russeifa", "الرصيفة"),
    ("SA", (24.7136, 46.6753), "riyadh", "الرياض"),
    ("SA", (21.4858, 39.1925), "jeddah", "jedda", "جدة", "جده"),
    ("SA", (21.3891, 39.8579), "mecca", "makkah", "مكة", "مكة المكرمة"),
    ("SA", (24.5247, 39.5692), "medina", "madinah", "المدينة", "المدينة المنورة"),
    ("SA", (26.4207, 50.0888), "dammam", "الدمام"),
    ("SA", (26.2172, 50.1971), "khobar", "al khobar", "الخبر"),
    ("AE", (25.2048, 55.2708), "dubai", "دبي"),
    ("AE", (24.4539, 54.3773), "abu dhabi", "أبوظبي", "ابوظبي", "أبو ظبي"),
    ("AE", (25.3463, 55.4209), "sharjah", "الشارقة"),
    ("AE", (24.2075, 55.7447), "al ain", "العين"),
    ("KW", (29.3759, 47.9774), "kuwait city", "kuwait", "الكويت", "مدينة الكويت"),
    ("QA", (25.2854, 51.5310), "doha", "الدوحة"),
    ("BH", (26.2285, 50.5860), "manama", "المنامة"),
    ("OM", (23.5880, 58.3829), "muscat", "مسقط"),
    ("EG", (30.0444, 31.2357), "cairo", "القاهرة"),
    ("EG", (31.2001, 29.9187), "alexandria", "الإسكندرية", "الاسكندرية"),
    ("EG", (30.0131, 31.2089), "giza", "الجيزة"),
    ("LB", (33.8938, 35.5018), "beirut", "بيروت"),
    ("IQ", (33.3152, 44.3661), "baghdad", "بغداد"),
    ("IQ", (36.1911, 44.0092), "erbil", "أربيل", "اربيل"),
    ("IQ", (30.5085, 47.7804), "basra", "البصرة"),
    ("PS", (31.9038, 35.2034), "ramallah", "رام الله"),
    ("PS", (32.2211, 35.2544), "nablus", "نابلس"),
    ("PS", (31.5326, 35.0998), "hebron", "الخليل"),
    ("PS", (31.5017, 34.4668), "gaza", "غزة"),
    ("SY", (33.5138, 36.2765), "damascus", "دمشق"),
    ("MA", (33.5731, -7.5898), "casablanca", "الدار البيضاء"),
    ("TN", (36.8065, 10.1815), "tunis", "تونس"),
    ("TR", (41.0082, 28.9784), "istanbul", "اسطنبول", "إسطنبول"),
]
_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = _AR_DIACRITICS.sub("", text).translate(_AR_FOLD)
    text = text.replace("'", "").replace("’", "")
    return re.sub(r"[^\w؀-ۿ]+", " ", text).strip()


_INDEX = {}
for _country, _point, *_names in _CITIES:
    for _name in _names:
        _INDEX.setdefault(_norm(_name), []).append((_country, _point))


def lookup(city: Optional[str], country_code: Optional[str] = None) -> Optional[Tuple[float, float]]:
    """A listed city's centre, or None. Accepts "Amman", "Amman, Jordan",
    "Amman - Khalda", "عمّان". The country breaks ties (عمان is also how
    Arabic writes Oman, the country, which is not listed here)."""
    if not city:
        return None
    country = (country_code or "").upper() or None
    text = _norm(city)
    candidates = [text] + [_norm(part) for part in re.split(r"[,\-–/|،]", city) if part.strip()]
    words = text.split()
    candidates += [" ".join(words[i:i + n]) for n in (3, 2, 1) for i in range(len(words) - n + 1)]
    for candidate in candidates:
        matches = _INDEX.get(candidate)
        if not matches:
            continue
        for match_country, point in matches:
            if country is None or match_country == country:
                return point
    return None

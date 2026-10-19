"""
Reads a product or menu-item name into the parts a price comparison needs:
what it is (core words), how much of it (quantity with a unit), how big
(size word) and what is added to it (extras such as "extra", "double",
"with fries").

Pure functions, English and Arabic, no I/O. The tier decision is made in
tiers.py from two of these; nothing here looks at a price.
"""
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

_AR_DIACRITICS = re.compile(r"[ً-ٰٟـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_LETTER = re.compile(r"[؀-ۿ]")

# --- units: (dimension, size of one unit in the dimension's base unit) -------------------------
# Base units: duration = minutes, weight = grams, volume = millilitres, count = pieces.
_UNITS: Dict[str, Tuple[str, float]] = {
    "min": ("duration", 1), "mins": ("duration", 1), "minute": ("duration", 1), "minutes": ("duration", 1),
    "دقيقه": ("duration", 1), "دقائق": ("duration", 1), "دقيقتين": ("duration", 2),
    "h": ("duration", 60), "hr": ("duration", 60), "hrs": ("duration", 60), "hour": ("duration", 60),
    "hours": ("duration", 60), "ساعه": ("duration", 60), "ساعات": ("duration", 60), "ساعتين": ("duration", 120),
    "g": ("weight", 1), "gm": ("weight", 1), "gram": ("weight", 1), "grams": ("weight", 1),
    "غرام": ("weight", 1), "جرام": ("weight", 1), "غ": ("weight", 1),
    "kg": ("weight", 1000), "kilo": ("weight", 1000), "kilos": ("weight", 1000), "كيلو": ("weight", 1000),
    "ml": ("volume", 1), "مل": ("volume", 1),
    "l": ("volume", 1000), "lt": ("volume", 1000), "liter": ("volume", 1000), "litre": ("volume", 1000),
    "liters": ("volume", 1000), "litres": ("volume", 1000), "لتر": ("volume", 1000),
    "pc": ("count", 1), "pcs": ("count", 1), "piece": ("count", 1), "pieces": ("count", 1),
    "قطعه": ("count", 1), "قطع": ("count", 1), "حبه": ("count", 1), "حبات": ("count", 1),
    "pack": ("count", 1), "packs": ("count", 1), "pk": ("count", 1),
    "people": ("count", 1), "persons": ("count", 1), "person": ("count", 1), "guests": ("count", 1),
    "اشخاص": ("count", 1), "شخص": ("count", 1),
    "m": ("length", 1), "meter": ("length", 1), "meters": ("length", 1), "metre": ("length", 1), "metres": ("length", 1),
    "متر": ("length", 1),
    "ton": ("weight", 1_000_000), "tons": ("weight", 1_000_000), "tonne": ("weight", 1_000_000),
    "tonnes": ("weight", 1_000_000), "طن": ("weight", 1_000_000),
    "heure": ("duration", 60), "heures": ("duration", 60),
    "day": ("day", 1), "days": ("day", 1), "jour": ("day", 1), "jours": ("day", 1), "journee": ("day", 1),
    "journees": ("day", 1), "يوم": ("day", 1),
    "month": ("month", 1), "months": ("month", 1), "mois": ("month", 1), "شهر": ("month", 1),
}
# A unit named without a number means one of it ("hour class", "ساعة").
_ONE_BY_DEFAULT = {"hour", "ساعه", "heure", "journee"}
# A number glued to one of these is a SPECIFICATION (a diameter, a storage size, a power), not a quantity to scale:
# "110 mm" and "110mm" must read the same, and "128GB" differs from "256GB".
_SPEC_UNITS = {"mm": "mm", "ملم": "mm", "cm": "cm", "سم": "cm", "inches": "in", "inch": "in", "in": "in", "انش": "in",
               "gb": "gb", "tb": "tb", "mb": "mb", "watt": "w", "w": "w", "kw": "kw", "v": "v", "mah": "mah", "hz": "hz"}
_SPEC = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(" + "|".join(sorted((re.escape(u) for u in _SPEC_UNITS), key=len, reverse=True)) + r")(?!\w)")
_PER_UNIT = re.compile(r"\bper\s+(?=(?:" + "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True)) + r")(?!\w))")
_PACK_OF = re.compile(r"\b(?:box|pack|bag|carton|case|set)\s+of\s+(\d+)")
_HALF = re.compile(r"\b(?:demi|half)[\s-]*(?=(?:journee|jour|day|hour|heure)\b)")
_SIZE_LETTER = re.compile(r"(?<!\w)(?:taille|size|مقاس)\s*(xxs|xs|s|m|l|xl|xxl|xxxl)(?!\w)")
_SIZE_LETTER_RANK = {"xxs": 0, "xs": 0, "s": 1, "m": 2, "l": 3, "xl": 4, "xxl": 4, "xxxl": 4}
_UNIT_PATTERN = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
_QUANTITY = re.compile(rf"(?<![\w.])(?:(\d+(?:\.\d+)?)\s*)?({_UNIT_PATTERN})(?!\w)")

# --- size words ------------------------------------------------------------------------------
# 0 mini, 1 small, 2 regular (also what an unstated size means), 3 large, 4 family.
REGULAR_SIZE = 2
_SIZES: Dict[str, int] = {
    "mini": 0, "ميني": 0,
    "small": 1, "junior": 1, "صغير": 1, "صغيره": 1,
    "petit": 1, "petite": 1, "moyen": 2, "grand": 3, "grande": 3,
    "regular": 2, "medium": 2, "وسط": 2, "عادي": 2, "عاديه": 2,
    "large": 3, "big": 3, "jumbo": 3, "كبير": 3, "كبيره": 3,
    "family": 4, "xl": 4, "xxl": 4, "عائلي": 4, "عائليه": 4,
}

# --- extras: words that say "this has more in it" ----------------------------------------------
_MARKERS: Dict[str, str] = {
    "extra": "extra", "اضافي": "extra", "اضافيه": "extra", "اكسترا": "extra",
    "double": "double", "دبل": "double", "مزدوج": "double", "triple": "triple", "ترايبل": "triple",
    "deluxe": "premium", "premium": "premium", "supreme": "premium", "royal": "premium", "gold": "premium",
    "vip": "premium", "ديلوكس": "premium", "بريميوم": "premium", "فاخر": "premium",
    "loaded": "loaded", "combo": "combo", "meal": "combo", "كومبو": "combo", "وجبه": "combo",
}
_CONNECTORS = {"with", "plus", "w", "includes", "including", "featuring", "avec", "مع", "ومع", "شامل", "يشمل", "تشمل"}
_IGNORED = {"the", "and", "of", "a", "an", "for", "our", "best", "new", "fresh", "per", "و", "في", "من", "على",
            # French connectors and noise
            "en", "de", "du", "des", "la", "le", "les", "et", "pour", "par",
            # a container or a service tag says how it is sold, not what it is
            "jar", "bottle", "tin", "bag", "can", "box", "pouch", "sachet", "tube", "service", "services",
            "taille", "pointure", "size", "مقاس"}


@dataclass(frozen=True)
class Quantity:
    dimension: str  # duration | weight | volume | count
    amount: float   # in the dimension's base unit
    text: str       # as written, for explanations ("30 min")
    unit_size: float = 1.0  # base units in the unit as written (60 for "hour")


@dataclass
class Offer:
    name: str
    core: List[str] = field(default_factory=list)
    withs: List[str] = field(default_factory=list)
    markers: FrozenSet[str] = frozenset()
    quantity: Optional[Quantity] = None
    size: Optional[int] = None  # None = not stated
    numbers: List[str] = field(default_factory=list)  # standalone numbers that are not a quantity: "SPF 50", "iPhone 15", "38"
    bare_number: Optional[float] = None  # a number with no unit ("35 class"), kept so tiers.py can read it as the other side's unit

    @property
    def words(self) -> List[str]:
        return [*self.core, *self.withs]

    @property
    def size_or_regular(self) -> int:
        return REGULAR_SIZE if self.size is None else self.size

    @property
    def head(self) -> Optional[str]:
        """The word naming what the thing is: last core word in English ("cheese burger"),
        first in Arabic ("برجر لحم")."""
        pool = [w for w in (self.core or self.withs) if not any(ch.isdigit() for ch in w)]  # not a spec like 256gb
        if not pool:
            return None
        arabic = sum(1 for w in pool if _ARABIC_LETTER.search(w)) > len(pool) / 2
        return pool[0] if arabic else pool[-1]


def _prep(text: str) -> str:
    text = (text or "").translate(_DIGITS).lower()
    text = _AR_DIACRITICS.sub("", text).translate(_AR_FOLD)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))  # émeraude = emeraude
    return text.replace("+", " with ").replace("&", " and ")


def _stem(word: str) -> str:
    if _ARABIC_LETTER.search(word):
        word = re.sub(r"^(وال|بال|فال|كال|لل|ال)(?=.{2,})", "", word)
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"  # fries -> fry
    if len(word) > 5 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]  # sandwiches -> sandwich
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


@lru_cache(maxsize=131072)
def same_word(a: str, b: str) -> bool:
    """Equal, or one letter apart in a long enough word (shawarma / shawerma)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if la < 5 or lb < 5:
        return False
    # A spelling variant is about as long: "beefshawarma" is not a spelling of "shawarma" (the ratio is exactly 0.8).
    # This also means the matcher never has to run for words whose lengths differ this much.
    if abs(la - lb) > 2 or 2 * min(la, lb) / (la + lb) < 0.8:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.8


def contains_word(word: str, words: Sequence[str]) -> bool:
    return any(same_word(word, other) for other in words)


def parse_quantity(prepped: str) -> Tuple[Optional[Quantity], str]:
    """The first "number + unit" in the text and the text with it removed."""
    for match in _QUANTITY.finditer(prepped):
        number, unit = match.group(1), match.group(2)
        if number is None and unit not in _ONE_BY_DEFAULT:
            continue
        dimension, per_unit = _UNITS[unit]
        value = float(number) if number is not None else 1.0
        if value <= 0:
            continue
        written = f"{number} {unit}" if number is not None else unit
        return Quantity(dimension, value * per_unit, written, float(per_unit)), prepped[:match.start()] + " " + prepped[match.end():]
    return None, prepped


def _normalize_specs(prepped: str):
    """Rewrites the notations that mean one thing in several spellings, and pulls out a size letter.
    Returns (text, size rank or None)."""
    text = re.sub(r"(?<=\d)-(?=[a-z؀-ۿ])", " ", prepped)          # "6-pack" -> "6 pack"
    text = _PACK_OF.sub(r"\1 pcs", text)                            # "box of 100" -> "100 pcs"
    text = _SPEC.sub(lambda m: m.group(1) + _SPEC_UNITS[m.group(2)], text)  # "110 mm" / "2 inch" / "128 GB" -> one token
    text = _HALF.sub("0.5 ", text)                                   # "demi-journee" -> "0.5 journee"
    text = _PER_UNIT.sub("1 ", text)                                 # "per kg" / "(per m)" -> "1 kg"
    size = None
    found = _SIZE_LETTER.search(text)
    if found:
        size = _SIZE_LETTER_RANK[found.group(1)]
        text = text[:found.start()] + " " + text[found.end():]
    return text, size


def parse_offer(name: str) -> Offer:
    prepped, letter_size = _normalize_specs(_prep(name))
    quantity, rest = parse_quantity(prepped)
    rest = re.sub(r"(?<=\d)\.(?=\d)", "p", rest)  # keep "1.2mm" one word
    words = re.sub(r"[^\w؀-ۿ]+", " ", rest).split()

    core: List[str] = []
    withs: List[str] = []
    markers = set()
    size: Optional[int] = letter_size
    bare_number: Optional[float] = None
    numbers: List[str] = []
    after_connector = False
    for word in words:
        if word in _CONNECTORS:
            after_connector = True
            continue
        if word in _SIZES:
            size = _SIZES[word]
            continue
        if word in _MARKERS:
            markers.add(_MARKERS[word])
            continue
        if word.isdigit():
            if len(word) <= 5 and int(word) > 0:
                numbers.append(str(int(word)))
                if bare_number is None and quantity is None and len(word) <= 4:
                    bare_number = float(word)
            continue
        if word in _IGNORED:
            continue
        stemmed = _stem(word)
        if len(stemmed) < 2:
            continue
        (withs if after_connector else core).append(stemmed)
    return Offer(name=name, core=core, withs=withs, markers=frozenset(markers), quantity=quantity, size=size, numbers=numbers, bare_number=bare_number)


def _merge_compounds(words: List[str], other_words: Sequence[str]) -> List[str]:
    """Adjacent words that spell one word on the other side are joined into that word
    ("cheese", "burger" -> "cheeseburger" when the other name says "cheeseburger")."""
    out: List[str] = []
    i = 0
    while i < len(words):
        if i + 1 < len(words):
            joined = words[i] + words[i + 1]
            match = next((w for w in other_words if joined == w or (abs(len(joined) - len(w)) <= 1 and same_word(joined, w))), None)
            if match is not None:
                out.append(match)
                i += 2
                continue
        out.append(words[i])
        i += 1
    return out


def reconcile_compounds(a: "Offer", b: "Offer") -> Tuple["Offer", "Offer"]:
    """Both names with compound spellings made the same on each side, so a space or no
    space ("cheeseburger" / "cheese burger") never decides whether two items match."""
    from dataclasses import replace

    def fix(x: "Offer", y: "Offer") -> "Offer":
        return replace(x, core=_merge_compounds(x.core, y.words), withs=_merge_compounds(x.withs, y.words))

    a2, b2 = fix(a, b), fix(b, a)
    return fix(a2, b2), fix(b2, a2)


def overlap(a: Sequence[str], b: Sequence[str]) -> float:
    """F1 of the words two names share (1.0 = same words, 0.0 = nothing in common)."""
    if not a or not b:
        return 0.0
    hits_a = sum(1 for w in a if contains_word(w, b))
    hits_b = sum(1 for w in b if contains_word(w, a))
    precision, recall = hits_a / len(a), hits_b / len(b)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)

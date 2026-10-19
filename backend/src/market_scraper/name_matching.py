"""
Business-name matching across Arabic, English and transliteration.

The plain difflib ratio (ai/pricing/matching.py::similarity) used with a 0.82
bar rejects a correct match whenever one side is Arabic and the other is the
same name in Latin letters ("شاورما أبو علي" vs "Abu Ali Shawerma"), or when
either side carries a generic word ("Restaurant", "مطعم") or differs by
spelling ("Qasr" / "Kasr", "Hummus" / "Humus"). This module scores two names
with several safe views and returns the best:

  plain       the existing ratio on the raw text (never lowered by this module)
  normalized  accents / Arabic diacritics / alef-hamza-taa-marbuta variants
              folded, generic business words and "al" removed
  translit    Arabic letters mapped to Latin, then compared as normalized
  skeleton    consonant skeleton of the transliteration (vowels dropped,
              q/c/k merged) - catches vowel and spelling variants; only
              trusted for skeletons of 4+ letters and capped below 1.0
  tokens      every distinctive word of the shorter name appears in the longer

Limit: a name whose consonant skeleton is under 4 letters ("Sufra" / "سفرة") is
not matched across scripts - too many unrelated names share 3 consonants.
It is deliberately conservative: two different names with the same generic
words ("Al Quds Bakery" / "Al Qasr Bakery") must stay below the bar. The
test file pins both directions.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List

_AR_DIACRITICS = re.compile(r"[ً-ْٰـ]")
_AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ﻻ": "لا"})
_AR_TO_LATIN = {
    "ا": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh", "د": "d", "ذ": "dh", "ر": "r", "ز": "z",
    "س": "s", "ش": "sh", "ص": "s", "ض": "d", "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "q", "ك": "k",
    "ل": "l", "م": "m", "ن": "n", "ه": "h", "و": "w", "ي": "y", "ء": "", "پ": "b", "چ": "ch", "گ": "g",
}
# Words every business name has; they carry no identity. (Arabic forms are post-fold.)
_GENERIC = {
    "restaurant", "restaurants", "cafe", "coffee", "shop", "store", "stores", "bakery", "sweets", "pharmacy", "market",
    "supermarket", "grill", "kitchen", "house", "center", "centre", "company", "co", "ltd", "llc", "trading", "group",
    "the", "and", "al", "el", "ال", "مطعم", "مطاعم", "كافيه", "مقهي", "قهوه", "محل", "متجر", "مخبز", "حلويات", "صيدليه",
    "سوبرماركت", "مركز", "شركه", "مجموعه", "و", "ابو", "abu", "abou", "bu",
}
_VOWELS = re.compile(r"[aeiouy]")


def _strip_marks(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


def normalize(text: str, drop_generic: bool = True) -> str:
    text = _strip_marks(_AR_DIACRITICS.sub("", (text or "").lower())).translate(_AR_FOLD)
    text = re.sub(r"[^\w؀-ۿ]+", " ", text)
    words = []
    for word in text.split():
        word = re.sub(r"^(ال|al-?|el-?)(?=.{3,})", "", word) if not word.isdigit() else word
        generic = drop_generic and (word in _GENERIC or (word[:2] == "لل" and word[2:] in _GENERIC)
                                    or (word[:1] in ("ل", "و", "ب") and word[1:] in _GENERIC))
        if word and not generic:
            words.append(word)
    return " ".join(words)


def transliterate(text: str) -> str:
    """Arabic letters -> Latin, other characters untouched."""
    return "".join(_AR_TO_LATIN.get(ch, ch) for ch in text)


def _word_skeleton(word: str) -> str:
    latin = transliterate(word).lower()
    latin = (latin.replace("ph", "f").replace("ck", "k").replace("kh", "x").replace("sh", "c").replace("dh", "z")
             .replace("th", "t").replace("gh", "g").replace("q", "k").replace("w", "u"))
    latin = re.sub(r"[^a-z0-9]", "", latin)
    consonants = re.sub(r"(.)\1+", r"\1", _VOWELS.sub("", latin))
    # A final h is the taa marbuta / a trailing -a spelling ("Habibah" / "Habiba" / "حبيبة").
    return consonants[:-1] if len(consonants) >= 3 and consonants.endswith("h") else consonants


def skeleton(text: str) -> str:
    """Order-independent consonant skeleton of a name: per word, transliterated,
    spelling variants merged, vowels and a final h dropped; words sorted."""
    return "".join(sorted(sk for sk in (_word_skeleton(w) for w in normalize(text).split()) if sk))


def _tokens(text: str) -> List[str]:
    return [t for t in transliterate(normalize(text)).split() if len(t) >= 2]


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def name_similarity(a: str, b: str) -> float:
    """0-1 similarity of two business names; never lower than the plain ratio."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    best = _ratio(a.lower(), b.lower())
    norm_a, norm_b = normalize(a), normalize(b)
    if norm_a and norm_b:
        best = max(best, _ratio(norm_a, norm_b))
        trans_a, trans_b = transliterate(norm_a), transliterate(norm_b)
        best = max(best, _ratio(trans_a, trans_b))
        skel_a, skel_b = skeleton(a), skeleton(b)
        if skel_a and skel_a == skel_b and len(skel_a) >= 4:
            best = max(best, 0.95)
        elif min(len(skel_a), len(skel_b)) >= 4:
            best = max(best, min(0.92, _ratio(skel_a, skel_b)))
        # Same distinctive words (each side's words match one-to-one), whatever the script.
        words_a, words_b = _tokens(a), _tokens(b)
        if words_a and len(words_a) == len(words_b) and all(
                any(_ratio(x, y) >= 0.85 or (_word_skeleton(x) == _word_skeleton(y) and len(_word_skeleton(x)) >= 4) for y in words_b)
                for x in words_a):
            best = max(best, 0.9)
    return round(min(best, 1.0), 4)

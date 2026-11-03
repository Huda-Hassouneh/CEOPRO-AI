"""
KEEL - Arabic text folding for SEARCH (never for storage or display).

Stored text keeps exactly what the customer wrote. Only the keys used to
match a question against documents are folded, so the same word matches
however it was typed:

- diacritics (tashkeel), superscript alef and tatweel are removed - Python's
  \\w does not match combining marks, so "إِنَّ" used to split into the
  meaningless tokens "إ" and "ن";
- hamza-carrying alef forms (أ إ آ ٱ) -> ا, alef maqsura ى -> ي, taa marbuta
  ة -> ه (the common keyboard variants: "اوقات خدمه" = "أوقات خدمة");
- Arabic-Indic / Persian digits -> 0-9 and the Arabic decimal / thousands
  separators / percent sign -> . , % ("١٤" = "14");
- Arabic presentation-form glyphs (U+FB50-FEFF, from badly made PDFs) ->
  base letters.

The same folding rag/understanding.py::_norm applies to questions; this
module makes it available to the document index without importing the
whole question-understanding layer.
"""
import re
import unicodedata

_DIACRITICS = re.compile("[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06edـ]")
_PRESENTATION = re.compile("[\ufb50-\ufdff\ufe70-\ufeff]")
_FOLD = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4", "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4", "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٫": ".", "٬": ",", "٪": "%",
})


def fold_for_search(text: str) -> str:
    text = _PRESENTATION.sub(lambda m: unicodedata.normalize("NFKC", m.group()), text or "")
    return _DIACRITICS.sub("", text).translate(_FOLD).lower()

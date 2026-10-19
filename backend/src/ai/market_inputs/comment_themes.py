"""
What customers talk about, read from the comments themselves: eight fixed themes, each a list of plain
keywords in English and Arabic. Deterministic - a theme is "mentioned" when a keyword appears in the text,
and nothing is generated or guessed. A comment can touch several themes.
"""
from typing import Dict, Iterable, List, Optional

THEMES: Dict[str, tuple] = {
    "service": ("service", "خدمة", "خدمه"),
    "waiting": ("waiting", "waited", "long wait", "wait time", "slow", "queue", "delay", "took forever", "too long", "انتظار", "بطيء", "بطيئ", "تأخير", "تاخير", "طابور"),
    "price": ("price", "expensive", "overpriced", "pricey", "cheap", "سعر", "أسعار", "اسعار", "غالي", "غالية", "رخيص", "مرتفع"),
    "quality": ("quality", "fresh", "stale", "cold", "tasty", "delicious", "taste", "جودة", "طازج", "بارد", "لذيذ", "طعم"),
    "cleanliness": ("clean", "dirty", "hygiene", "smell", "نظيف", "نظافة", "وسخ", "قذر", "رائحة"),
    "staff": ("staff", "waiter", "waitress", "cashier", "manager", "employee", "rude", "موظف", "نادل", "مدير", "وقح"),
    "delivery": ("delivery", "deliver", "courier", "rider", "توصيل", "سائق"),
    "availability": ("sold out", "out of stock", "unavailable", "closed", "available", "نفد", "غير متوفر", "مغلق", "متوفر"),
}
THEME_KEYS = tuple(THEMES)
# Reading the most-agreed-with comments only: a bounded, predictable cost however many are stored.
MAX_COMMENTS_READ = 500


def ilike_patterns(theme: str) -> List[str]:
    """SQL `ILIKE ANY` patterns for a theme (LIKE wildcards in a keyword are escaped)."""
    return ["%" + k.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%" for k in THEMES[theme]]


def themes_in(text: Optional[str]) -> List[str]:
    lowered = (text or "").lower()
    return [theme for theme, words in THEMES.items() if any(w in lowered for w in words)]


def summarise(rows: Iterable[tuple]) -> List[dict]:
    """rows: (review_id, text, sentiment, likes). One entry per theme that was mentioned: how many comments,
    how many were negative / positive, and the most agreed-with example. Most complaints first."""
    stats: Dict[str, dict] = {}
    for review_id, text, sentiment, likes in rows:
        for theme in themes_in(text):
            entry = stats.setdefault(theme, {"theme": theme, "mentions": 0, "negative": 0, "positive": 0, "example": None})
            entry["mentions"] += 1
            label = (sentiment or "").lower()
            entry["negative"] += label == "negative"
            entry["positive"] += label == "positive"
            if entry["example"] is None or (likes or 0) > entry["example"]["people_agreeing"]:
                entry["example"] = {"id": str(review_id), "text": (text or "")[:240], "people_agreeing": int(likes or 0)}
    return sorted(stats.values(), key=lambda e: (-e["negative"], -e["mentions"], e["theme"]))

import sys
sys.path.insert(0, '.')
from src.ai.rag import advisor, understanding as U
import math


def wilson(k, n, z=1.96):
    """95% Wilson score interval for k successes out of n, in percent."""
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n; c = p + z * z / (2 * n); h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (round(100 * (c - h) / d, 1), round(100 * (c + h) / d, 1))

def fields(u, answerable):
    per = [(p["start"], p["end"]) for p in u.slots.get("periods") or []]
    return {"intents": set(u.intents), "periods": per, "days": u.slots.get("period_days"),
            "products": {p["name"] for p in u.slots.get("products") or []},
            "ranking": bool(u.slots.get("top_product")) or bool(u.slots.get("ranking_requested"))
                       or bool(advisor._RANKING.search(U._norm(u.effective_question))), "answerable": answerable}

def check(c, g):
    prob = set()
    if "intents" in c and not set(c["intents"]) <= g["intents"]: prob.add("intent_recall")
    if "intents" in c and g["intents"] - set(c["intents"]) - set(c.get("allowed", set())): prob.add("intent_precision")
    if "periods" in c and sorted(map(tuple, c["periods"])) != sorted(g["periods"]): prob.add("period")
    if "days" in c and g["days"] != c["days"]: prob.add("period")
    if "products" in c and not set(c["products"]) <= g["products"]: prob.add("product")
    if "top" in c and g["ranking"] != c["top"]: prob.add("ranking")
    if "answerable" in c and g["answerable"] != c["answerable"]: prob.add("answerable")
    return prob


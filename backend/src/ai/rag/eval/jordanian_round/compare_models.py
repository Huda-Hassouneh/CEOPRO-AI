"""Same development data, same prompt, same machine: every model's saved readings scored identically.
  python compare_models.py <scratchpad> <pool: validation|sealed_v2|sealed_v2_mini> <tag> [<tag> ...]"""
import collections, copy, json, sys
import numpy as np
sys.path.insert(0, "."); sys.path.insert(0, sys.argv[1])
from src.ai.rag import llm_understanding as L, understanding as U
from src.ai.rag.eval.understanding_benchmark import CATALOG, TODAY
import val_checks as V
from validation_set import VALIDATION
from sealed_set_v2 import SEALED_V2

pool = sys.argv[2]
cases = {"validation": VALIDATION, "sealed_v2": SEALED_V2, "sealed_v2_mini": SEALED_V2[::4]}[pool]
EMPTY = {"intents": [], "periods": [], "period_days": None, "products": [], "ranking": False, "small_talk": False}

def alone_fields(r):
    r = r or EMPTY
    return {"intents": set(r["intents"]), "periods": [(p["start"], p["end"]) for p in r["periods"]], "days": r["period_days"],
            "products": {p["name"] for p in r["products"]}, "ranking": r["ranking"], "answerable": not r["small_talk"]}

print(f"pool {pool}, n={len(cases)} (Jordanian {sum(c['lang'] == 'jo' for c in cases)})")
print(f"{'model':14} {'gated pipeline':>22} {'model always':>13} {'model alone':>12} {'JO gated':>9} {'JO alone':>9} "
      f"{'median s':>8} {'P95 s':>6} {'max s':>6} {'invalid':>7}")
for tag in sys.argv[3:]:
    try:
        data = {d["q"]: d for d in json.load(open(f"{sys.argv[1]}/readings_{pool}_{tag}.json"))}
    except FileNotFoundError:
        print(f"{tag:14} (not run)"); continue
    gated = always = alone = jo_g = jo_a = 0
    for c in cases:
        u = U.understand(c["q"], catalog=CATALOG, company_currency="JOD", today=TODAY)
        ans, had = U.is_answerable(c["q"]), bool(u.intents)
        r = data[c["q"]]["reading"]
        rg = r if L.needs_model(u, c["q"]) else None
        g_ok = not V.check(c, V.fields(L.fill_gaps(copy.deepcopy(u), rg), L.answerable(ans, had, rg)))
        a_ok = not V.check(c, V.fields(L.fill_gaps(copy.deepcopy(u), r), L.answerable(ans, had, r)))
        m_ok = not V.check(c, alone_fields(r))
        gated += g_ok; always += a_ok; alone += m_ok
        if c["lang"] == "jo":
            jo_g += g_ok; jo_a += m_ok
    n = len(cases); nj = sum(c["lang"] == "jo" for c in cases)
    secs = np.array([d["sec"] for d in data.values()]); invalid = sum(d["reading"] is None for d in data.values())
    print(f"{tag:14} {gated:>4}/{n} {100*gated/n:5.1f}% {str(V.wilson(gated, n)):>11} {100*always/n:12.1f}% {100*alone/n:11.1f}% "
          f"{jo_g:>4}/{nj:<4} {jo_a:>4}/{nj:<4} {np.median(secs):8.1f} {np.percentile(secs, 95):6.1f} {secs.max():6.1f} {invalid:>4}/{n}")

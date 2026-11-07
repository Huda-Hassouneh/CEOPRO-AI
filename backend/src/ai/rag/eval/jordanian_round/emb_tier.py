import sys, collections, copy, json
import numpy as np
exec(open(sys.argv[1] + "/emb_probe.py").read().split("for name, pool in ((\"val_jo2\"")[0])
from src.ai.rag import llm_understanding as L, understanding as U
import val_checks as V
from dev_jo2 import DEV_JO2
def tiered(pool, diag, conf):
    model_ok = {x["q"]: not x["fails"] for x in json.load(open(f"{sys.argv[1]}/{diag}"))} if diag else None
    ok = calls = n = 0
    for c in pool:
        u = U.understand(c["q"], catalog=B.CATALOG, company_currency="JOD", today=B.TODAY); n += 1
        ans, had = U.is_answerable(c["q"]), bool(u.intents)
        if not L.needs_model(u, c["q"]):
            ok += not V.check(c, V.fields(u, ans)); continue
        q = emb([c["q"]])[0]; sims = E @ q; top = np.argsort(-sims)[:5]; votes = collections.Counter()
        for i in top: votes[label(train[i])] += sims[i]
        (pred, w), = votes.most_common(1); share = w / sum(votes.values())
        if sims[top[0]] >= conf[0] and share >= conf[1]:
            r = {"intents": [] if pred == {"small_talk"} else sorted(pred), "periods": [], "period_days": None, "products": [], "ranking": False, "small_talk": pred == {"small_talk"}}
            ok += not V.check(c, V.fields(L.fill_gaps(copy.deepcopy(u), r), L.answerable(ans, had, r)))
        else:
            calls += 1; ok += model_ok[c["q"]] if model_ok else 0
    return ok, n, calls
# choose thresholds on DEV only (leave-one-out on dev_jo2 against the rest of the dev examples is overkill; grid on val is NOT allowed)
for conf in ((0.0, 0.0), (0.80, 0.6), (0.85, 0.6), (0.85, 0.8), (0.90, 0.8), (2, 2)):
    a = tiered(VAL_JO2, "diag_val_jo2_r3.json", conf); b = tiered(VALIDATION, "diag_validation_set_r3.json", conf)
    print(conf, f"val_jo2 {a[0]}/{a[1]} model calls {a[2]} | validation {b[0]}/{b[1]} model calls {b[2]}")

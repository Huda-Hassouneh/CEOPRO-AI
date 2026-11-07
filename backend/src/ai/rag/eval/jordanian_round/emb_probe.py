"""Intent from meaning: nearest development examples by multilingual embedding (granite-278m, local GGUF)."""
import sys, time, collections, resource
import numpy as np
sys.path[:0] = [".", sys.argv[1]]
from llama_cpp import Llama
from dev_jo2 import DEV_JO2; from val_jo2 import VAL_JO2; from validation_set import VALIDATION
from sealed_set import SEALED; from sealed_set_v2 import SEALED_V2
from src.ai.rag.eval import understanding_benchmark as B
m = Llama(model_path="/var/lib/keelpg/models/granite-embedding-multilingual-278m-f16.gguf", embedding=True, verbose=False, n_threads=4, n_ctx=512)
def emb(texts):
    out = []
    for t in texts:
        v = np.array(m.embed(t), dtype=np.float32); v = v.mean(0) if v.ndim == 2 else v; out.append(v / np.linalg.norm(v))
    return np.stack(out)
def label(c): return frozenset(c.get("intents", ())) if c.get("answerable", True) else frozenset({"small_talk"})
train = [c for c in DEV_JO2 + SEALED + SEALED_V2 if label(c)]
t = time.perf_counter(); E = emb([c["q"] for c in train]); print(f"embedded {len(train)} dev examples in {time.perf_counter()-t:.1f}s")
for name, pool in (("val_jo2", VAL_JO2), ("validation_set", VALIDATION)):
    pool = [c for c in pool if label(c)]
    t = time.perf_counter(); Q = emb([c["q"] for c in pool]); per = (time.perf_counter() - t) / len(pool)
    ok = 0
    for c, q in zip(pool, Q):
        sims = E @ q; top = np.argsort(-sims)[:5]; votes = collections.Counter()
        for i in top: votes[label(train[i])] += sims[i]
        pred = votes.most_common(1)[0][0]; ok += pred == label(c) or (pred <= label(c) | frozenset(c.get("allowed", ())) and label(c) <= pred)
    print(f"{name}: exact intent set {ok}/{len(pool)} = {100*ok/len(pool):.1f}% | {1000*per:.0f} ms per question")
print(f"peak memory {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")

# --- as the fallback reader behind the rules (only where the gate would ask the model)
import copy, json
from src.ai.rag import llm_understanding as L, understanding as U
import val_checks as V
for name, pool, diag in (("val_jo2", VAL_JO2, "diag_val_jo2_r3.json"), ("validation_set", VALIDATION, "diag_validation_set_r3.json")):
    model_ok = {x["q"]: not x["fails"] for x in json.load(open(f"{sys.argv[1]}/{diag}"))}
    rules_ok = emb_ok = llm_ok = asked = 0
    for c in pool:
        u = U.understand(c["q"], catalog=B.CATALOG, company_currency="JOD", today=B.TODAY)
        ans, had = U.is_answerable(c["q"]), bool(u.intents); r_ok = not V.check(c, V.fields(u, ans))
        rules_ok += r_ok
        if not L.needs_model(u, c["q"]):
            emb_ok += r_ok; llm_ok += model_ok[c["q"]]; continue
        asked += 1; llm_ok += model_ok[c["q"]]
        q = emb([c["q"]])[0]; sims = E @ q; votes = collections.Counter()
        for i in np.argsort(-sims)[:5]: votes[label(train[i])] += sims[i]
        pred = votes.most_common(1)[0][0]
        reading = {"intents": [] if pred == {"small_talk"} else sorted(pred), "periods": [], "period_days": None, "products": [],
                   "ranking": False, "small_talk": pred == {"small_talk"}}
        emb_ok += not V.check(c, V.fields(L.fill_gaps(copy.deepcopy(u), reading), L.answerable(ans, had, reading)))
    n = len(pool); print(f"{name}: rules only {100*rules_ok/n:.1f}% | rules+embeddings {100*emb_ok/n:.1f}% | rules+Qwen3-4B {100*llm_ok/n:.1f}% | fallback used on {asked}")

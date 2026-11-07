"""Final evaluation of the gated pipeline on a SEALED set - aggregate output only (no per-question lines).

  python final_eval.py <scratchpad> <set: v3|jo> <model.gguf> <tag>

Pipeline = the product path: understanding.understand -> llm_understanding.needs_model -> (model) -> fill_gaps.
The model runs in-process with llama.cpp (same prompt and examples as the product module)."""
import collections, copy, json, resource, sys, time
import numpy as np
sys.path.insert(0, "."); sys.path.insert(0, sys.argv[1])
from llama_cpp import Llama
from src.ai.rag import llm_client, llm_understanding as L, understanding as U
from src.ai.rag.eval.understanding_benchmark import CATALOG, TODAY
import val_checks as V

which, model_path, tag = sys.argv[2], sys.argv[3], sys.argv[4]
if which == "v3":
    from sealed_set_v3 import SEALED_V3 as CASES
elif which == "jo2":
    from sealed_jo2 import SEALED_JO2 as CASES
else:
    from sealed_jo import SEALED_JO as CASES

llm = Llama(model_path=model_path, n_ctx=4096, n_threads=4, verbose=False)
calls = {"n": 0}
def in_process(messages, temperature=0, max_tokens=200, json_mode=False, **_):
    calls["n"] += 1
    r = llm.create_chat_completion(messages=messages, temperature=temperature, max_tokens=max_tokens,
                                   **({"response_format": {"type": "json_object"}} if json_mode else {}))
    return r["choices"][0]["message"]["content"]
llm_client.chat_completion = in_process
L.read("warm-up question", CATALOG, TODAY)  # load weights and cache the fixed prompt prefix once

def complexity(c):
    if "cx" in c:
        return c["cx"]
    n_periods = len(c.get("periods", []))
    return "compound" if n_periods > 1 or len(c.get("intents", set())) > 1 else "simple"

def domain(c):
    if "dom" in c:
        return c["dom"]
    if c.get("answerable") is False:
        return "small_talk"
    return sorted(c.get("intents", {"?"}))[0]

rows = []
for c in CASES:
    t = time.perf_counter()
    u = U.understand(c["q"], catalog=CATALOG, company_currency="JOD", today=TODAY)
    ans, had = U.is_answerable(c["q"]), bool(u.intents)
    asked = L.needs_model(u, c["q"])
    before = calls["n"]
    reading = L.read(c["q"], CATALOG, TODAY) if asked else None
    h = L.fill_gaps(copy.deepcopy(u), reading)
    fails = V.check(c, V.fields(h, L.answerable(ans, had, reading)))
    rows.append({"lang": c["lang"], "dom": domain(c), "cx": complexity(c), "ok": not fails, "fails": sorted(fails),
                 "sec": time.perf_counter() - t, "asked": asked, "invalid": asked and reading is None,
                 "model_calls": calls["n"] - before})

def summary(subset):
    k = sum(r["ok"] for r in subset); n = len(subset)
    return f"{k}/{n} = {100*k/max(1,n):.1f}% CI {V.wilson(k, n)}"

secs = np.array([r["sec"] for r in rows]); simple = np.array([r["sec"] for r in rows if r["cx"] == "simple"])
print(f"== {which} set, {tag}, n={len(rows)}")
print("overall:", summary(rows))
for key in ("lang", "cx", "dom"):
    groups = collections.defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    print(f"by {key}:", "; ".join(f"{g} {summary(v)}" for g, v in sorted(groups.items())))
print("errors by field:", dict(collections.Counter(f for r in rows for f in r["fails"])))
print(f"latency: median {np.median(secs):.2f}s  P95 {np.percentile(secs, 95):.2f}s  max {secs.max():.2f}s | "
      f"simple questions median {np.median(simple):.2f}s P95 {np.percentile(simple, 95):.2f}s | "
      f"rules-only questions median {np.median([r['sec'] for r in rows if not r['asked']]):.3f}s")
print(f"model asked on {sum(r['asked'] for r in rows)}/{len(rows)} questions; invalid model answers "
      f"{sum(r['invalid'] for r in rows)}; total model calls {sum(r['model_calls'] for r in rows)} (retries included)")
print(f"peak memory of this process: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")

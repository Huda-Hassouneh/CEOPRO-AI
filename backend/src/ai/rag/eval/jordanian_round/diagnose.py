"""Per-question diagnosis of a scored set (sealed_jo is spent: diagnosis only, never re-cited as independent).
  python diagnose.py <scratchpad> <module> <VAR> <model.gguf> <out.json>"""
import copy, importlib, json, resource, sys, time
sys.path.insert(0, "."); sys.path.insert(0, sys.argv[1])
from llama_cpp import Llama
from src.ai.rag import llm_client, llm_understanding as L, understanding as U
from src.ai.rag.eval.understanding_benchmark import CATALOG, TODAY
import val_checks as V
cases = getattr(importlib.import_module(sys.argv[2]), sys.argv[3])
llm = Llama(model_path=sys.argv[4], n_ctx=4096, n_threads=4, verbose=False)
def chat(messages, temperature=0, max_tokens=200, json_mode=False, **_):
    return llm.create_chat_completion(messages=messages, temperature=temperature, max_tokens=max_tokens,
        **({"response_format": {"type": "json_object"}} if json_mode else {}))["choices"][0]["message"]["content"]
llm_client.chat_completion = chat
out = []
L.read("warm-up question", CATALOG, TODAY)
for c in cases:
    t = time.perf_counter()
    u = U.understand(c["q"], catalog=CATALOG, company_currency="JOD", today=TODAY)
    rules = sorted(u.intents); ans, had = U.is_answerable(c["q"]), bool(u.intents)
    asked = L.needs_model(u, c["q"]); r = L.read(c["q"], CATALOG, TODAY) if asked else None
    h = L.fill_gaps(copy.deepcopy(u), r); f = V.fields(h, L.answerable(ans, had, r))
    out.append({"q": c["q"], "dom": c.get("dom"), "cx": c.get("cx"), "expected": sorted(c.get("intents", [])),
                "allowed": sorted(c.get("allowed", [])), "rules": rules, "asked": asked,
                "model": r and r["intents"], "final": sorted(f["intents"]), "fails": sorted(V.check(c, f)), "sec": time.perf_counter() - t,
                "invalid": asked and r is None})
print(f"peak memory {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024:.0f} MB")
json.dump(out, open(sys.argv[5], "w"), ensure_ascii=False, indent=1)

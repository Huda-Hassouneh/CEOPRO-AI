"""Rules-only score (no model) + list which questions the gate would send to the model.
  python rules_eval.py <scratchpad> <module> <VAR> [-v]"""
import importlib, sys, collections
sys.path.insert(0, "."); sys.path.insert(0, sys.argv[1])
from src.ai.rag import llm_understanding as L, understanding as U
from src.ai.rag.eval.understanding_benchmark import CATALOG, TODAY
import val_checks as V
cases = getattr(importlib.import_module(sys.argv[2]), sys.argv[3]); verbose = "-v" in sys.argv
ok = asked = 0; fields = collections.Counter()
for c in cases:
    u = U.understand(c["q"], catalog=CATALOG, company_currency="JOD", today=TODAY)
    f = V.check(c, V.fields(u, U.is_answerable(c["q"]))); g = L.needs_model(u, c["q"])
    ok += not f; asked += g; fields.update(f)
    if verbose and (f or g):
        print(("ASK " if g else "    ") + ("FAIL " if f else "ok   "), c["q"], "| exp", sorted(c.get("intents", [])),
              "| rules", sorted(u.intents), sorted(f))
print(f"{sys.argv[2]}: rules-only {ok}/{len(cases)} = {100*ok/len(cases):.1f}%  gate asks {asked}  fields {dict(fields)}")

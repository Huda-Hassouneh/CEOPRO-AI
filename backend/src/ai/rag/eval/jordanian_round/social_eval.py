"""Score conversation.classify + social_reply on a social set.  python social_eval.py <scratchpad> <DEV|VAL> [-v]"""
import re, sys, time
sys.path[:0] = [".", sys.argv[1]]
from src.ai.rag import conversation as C
import social_sets
cases = {"DEV": social_sets.SOCIAL_DEV, "VAL": social_sets.SOCIAL_VAL}[sys.argv[2]]
ok = 0; fails = []; secs = []
for c in cases:
    t = time.perf_counter(); turn = C.classify(c["q"], has_context=False)
    reply = " ".join(C.social_reply(turn, c["q"])[0]) if turn.kind == C.SOCIAL else ""; secs.append(time.perf_counter() - t)
    good = (turn.kind == C.SOCIAL) == (c["kind"] == "social")
    if c.get("q_kept"): good = good and bool(turn.remainder.strip()) and turn.remainder.strip() != c["q"].strip() or (good and not turn.acts)
    if c["kind"] == "social" and good:
        arabic_in = bool(re.search(r"[؀-ۿ]", c["q"])); arabic_out = bool(re.search(r"[؀-ۿ]", reply))
        good = not re.search(r"\d{2,}|\d[.,]\d", reply) and (arabic_in == arabic_out or not re.search(r"[A-Za-z؀-ۿ]", c["q"]))
    ok += good
    if not good: fails.append((c["q"], c["kind"], turn.kind, turn.acts, turn.remainder[:30], reply[:50]))
n = len(cases); secs.sort()
print(f"social {sys.argv[2]}: {ok}/{n} = {100*ok/n:.1f}% | median {1000*secs[n//2]:.2f} ms max {1000*secs[-1]:.2f} ms")
if "-v" in sys.argv:
    for f in fails: print("  FAIL", f)

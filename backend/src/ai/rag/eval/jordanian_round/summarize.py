"""Aggregate a diagnose.py JSON: accuracy + Wilson CI overall and by cx/dom, error fields, latency, model use.
  python summarize.py <scratchpad> <json> [-v]"""
import collections, json, sys
import numpy as np
sys.path.insert(0, sys.argv[1]); from val_checks import wilson
d = json.load(open(sys.argv[2]))
def s(v): k = sum(not x["fails"] for x in v); return f"{k}/{len(v)} = {100*k/len(v):.1f}% CI {wilson(k, len(v))}"
print(sys.argv[2].split("/")[-1], "overall:", s(d))
for key in ("cx", "dom"):
    g = collections.defaultdict(list); [g[x[key]].append(x) for x in d]
    print(f" by {key}:", "; ".join(f"{a} {s(b)}" for a, b in sorted(g.items(), key=lambda t: str(t[0]))))
print(" error fields:", dict(collections.Counter(f for x in d for f in x["fails"])))
if "sec" in d[0]:
    sec = np.array([x["sec"] for x in d]); asked = [x["sec"] for x in d if x["asked"]]
    print(f" latency median {np.median(sec):.3f}s P95 {np.percentile(sec,95):.2f}s max {sec.max():.2f}s | model-asked median "
          f"{np.median(asked) if asked else 0:.1f}s | asked {len(asked)}/{len(d)} invalid {sum(x.get('invalid',0) for x in d)}")
if "-v" in sys.argv:
    for x in d:
        if x["fails"]:
            print("  FAIL", x["q"], "| exp", x["expected"], "| rules", x["rules"], "| model", x["model"], "| final", x["final"], x["fails"])

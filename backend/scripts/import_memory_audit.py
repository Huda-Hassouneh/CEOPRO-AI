"""
Which third-party libraries make up a process's resident memory at startup,
and which of our modules first imports each one.

    python -m scripts.import_memory_audit src.ai.main
    python -m scripts.import_memory_audit src.market_scraper.analysis_worker

Wraps __import__ and records the resident set size (VmRSS, Linux) around the
first import of every top-level package. "own" is the memory added by that
package minus what the other top-level packages it imported added, so the
column sums to the total; "via" is the first module of ours on the import
stack at that moment (nested imports are charged to the module of ours
that started the chain), and the second table totals memory per such
module. Nothing is loaded that the target module would not load anyway.
"""
import builtins
import importlib
import sys
from collections import defaultdict


def rss_mb() -> float:
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    return 0.0


def main(target: str, top: int = 30) -> None:
    real_import = builtins.__import__
    stack, own, via = [], defaultdict(float), {}

    def tracking_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0] if level == 0 else None
        first = root is not None and root not in sys.modules and root not in via
        if not first:
            return real_import(name, globals, locals, fromlist, level)
        importer = (globals or {}).get("__name__", "?")
        # Charge nested imports (sklearn imported by xgboost) to the module of
        # ours that started the chain.
        via[root] = importer if importer.startswith("src.") or not stack else via[stack[-1][0]]
        stack.append([root, rss_mb(), 0.0])
        try:
            return real_import(name, globals, locals, fromlist, level)
        finally:
            name_, before, children = stack.pop()
            inclusive = rss_mb() - before
            own[name_] += inclusive - children
            if stack:
                stack[-1][2] += inclusive

    start = rss_mb()
    builtins.__import__ = tracking_import
    try:
        importlib.import_module(target)
    finally:
        builtins.__import__ = real_import
    total = rss_mb()
    print(f"{target}: interpreter {start:.0f} MB, after import {total:.0f} MB (+{total - start:.0f} MB)\n")
    print(f"{'package':28} {'own MB':>7}  first imported via")
    for name, mb in sorted(own.items(), key=lambda kv: -kv[1])[:top]:
        print(f"{name:28} {mb:7.1f}  {via.get(name, '')}")
    by_module = defaultdict(float)
    for name, mb in own.items():
        by_module[via.get(name, "?")] += mb
    print(f"\n{'our module that pulled it in':52} {'MB':>6}")
    for module, mb in sorted(by_module.items(), key=lambda kv: -kv[1])[:top]:
        if mb >= 1:
            print(f"{module:52} {mb:6.1f}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "src.ai.main")

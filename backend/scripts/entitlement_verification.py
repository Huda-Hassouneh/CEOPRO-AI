"""Verify existing entitlement authority without importing AI model endpoints.

From backend: python -m scripts.entitlement_verification inventory
             python -m scripts.entitlement_verification test [--database]
This is verification tooling, never middleware or a replacement policy engine.
"""

import argparse
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from scripts.billing_verification import BACKEND, validate_test_environment


def route_inventory(backend: Path = BACKEND) -> list[dict]:
    """Enumerate main's statically registered routes and direct call evidence.

    Calls are evidence, not a guarantee of enforcement: helpers can enforce
    transitively, and the presence of a call does not prove every branch uses it.
    No application imports, connections, secrets, or model loads are involved.
    """
    main = ast.parse((backend / "src/ai/main.py").read_text())
    included = {}
    for node in ast.walk(main):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "include_router"
            and node.args
        ):
            name = ast.unparse(node.args[0]).split(".")[0]
            included[name] = [
                ast.unparse(k.value) for k in node.keywords if k.arg == "dependencies"
            ]
    routes = []
    for name, gates in sorted(included.items()):
        file = backend / "src/ai/routers" / f"{name}.py"
        tree = ast.parse(file.read_text())
        functions = {
            n.name: n
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        prefix = ""
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and ast.unparse(node.func) == "APIRouter":
                prefix = next(
                    (
                        ast.literal_eval(k.value)
                        for k in node.keywords
                        if k.arg == "prefix"
                    ),
                    "",
                )
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(
                    dec.func, ast.Attribute
                ):
                    continue
                if ast.unparse(dec.func.value) != "router" or dec.func.attr not in {
                    "get",
                    "post",
                    "put",
                    "patch",
                    "delete",
                    "options",
                    "head",
                }:
                    continue
                calls = sorted(
                    {
                        ast.unparse(c.func)
                        for c in ast.walk(node)
                        if isinstance(c, ast.Call)
                    }
                )
                visited, pending = set(), list(calls)
                helper_checks = set()
                while pending:
                    helper = pending.pop()
                    if helper in visited or helper not in functions:
                        continue
                    visited.add(helper)
                    for call in ast.walk(functions[helper]):
                        if isinstance(call, ast.Call):
                            target = ast.unparse(call.func)
                            pending.append(target)
                            if target.startswith(("usage.", "credits.")):
                                helper_checks.add(target)
                routes.append(
                    {
                        "method": dec.func.attr.upper(),
                        "path": prefix + ast.literal_eval(dec.args[0]),
                        "source": str(file.relative_to(backend)),
                        "line": node.lineno,
                        "handler": node.name,
                        "tenant_dependency": "get_tenant_context"
                        in ast.unparse(node.args),
                        "same_file_helper_checks": sorted(helper_checks),
                        "router_dependencies": gates,
                        "route_dependencies": [
                            ast.unparse(k.value)
                            for k in dec.keywords
                            if k.arg == "dependencies"
                        ],
                        "direct_security_calls": [
                            c
                            for c in calls
                            if c.startswith(("usage.", "credits."))
                            or c in {"get_tenant_context", "get_current_user"}
                        ],
                        "calls": calls,
                    }
                )
    return sorted(routes, key=lambda r: (r["path"], r["method"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("inventory", "test"))
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    if args.command == "inventory":
        print(
            json.dumps(
                {
                    "scope": "static main router registrations; transitive enforcement needs review",
                    "routes": route_inventory(),
                },
                indent=2,
            )
        )
        return 0
    env = dict(os.environ)
    validate_test_environment(env, database=args.database)
    env["BILLING_DATABASE_TESTS"] = "1" if args.database else "0"
    env["KEEL_TEST_DISABLE_METERING"] = "0"
    env["UNASSIGNED_PLAN_ACCESS"] = "none"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if not args.database:
        env.pop("BILLING_TEST_DATABASE_URL", None)
        env.pop("DATABASE_URL", None)
        env.pop("AI_TEST_DATABASE_URL", None)
    with tempfile.TemporaryDirectory(prefix="keel-entitlement-pytest-") as cache:
        files = (
            ["tests/entitlements"]
            if args.database
            else [
                "tests/entitlements/test_policy.py",
                "tests/entitlements/test_routes.py",
            ]
        )
        return subprocess.call(
            [sys.executable, "-m", "pytest", "-q", "-o", f"cache_dir={cache}", *files],
            cwd=BACKEND,
            env=env,
        )


if __name__ == "__main__":
    raise SystemExit(main())

"""
Real image-generation benchmark for every image provider and model KEEL is
configured with (src/ai/marketing/image_generation.py). Each model is
measured on its own, with real requests through KEEL's own provider code
(the same request building, response parsing, image checks and cropping the
app uses), and the pictures are saved so their quality can be judged by eye.

Nothing is guessed: a provider with no credentials (or not reachable) is
reported as SKIPPED with the reason, never as a result. No tenant, campaign
or database row is touched - the calls go straight to the providers, not
through a company's AI Credits - so this costs only what the provider
itself charges for the images (the free providers' free allowances).

For each model it reports: requests, successes, failures (and why), average,
median and 95th-percentile seconds per image, the fastest and slowest, the
size the provider returned and the size after cropping to the format, the
file type, and whether it met the target (default 15 s, at P95).

  (in backend/) python -m scripts.benchmark_image_providers \\
      [--runs 5] [--formats SQUARE,STORY] [--providers cloudflare,huggingface] \\
      [--target 15] [--out benchmark-images] [--prompt "..."]

Credentials are read exactly as the app reads them (CLOUDFLARE_ACCOUNTS or
CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN, HUGGINGFACE_API_TOKEN(S),
TOGETHER_API_KEYS, GEMINI_API_KEYS, POLLINATIONS_API_KEYS, HORDE_API_KEYS
(anonymous AI Horde when unset), LOCAL_IMAGE_BASE_URL(S)). Each Cloudflare
and Hugging Face model in the app's model list is measured separately.
Writes <out>/report.json, <out>/report.md and the pictures to <out>/.
"""
import argparse
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from src.ai.marketing import image_generation as ig

DEFAULT_PROMPT = (
    "A 1 litre glass bottle of cold-pressed extra virgin olive oil from northern Jordan with a plain cream label, "
    "standing on a rustic olive-wood board beside a small bowl of green olives and a sprig of olive leaves, "
    "warm morning window light, shallow depth of field."
)

# As KEEL calls each one today (one picture per request). Where the
# provider's API can return several pictures in one request, the app does
# not use it; that is noted, not measured.
PICTURES_PER_REQUEST = {
    "cloudflare": "1 (API returns one image)",
    "huggingface": "1 (text-to-image returns one image)",
    "together": "1 as called (API accepts n)",
    "gemini": "1 as called",
    "pollinations": "1 (one image per URL)",
    "aihorde": "1 as called (API accepts n)",
    "local": "1 as called (server accepts n=1 only)",
}


def percentile(values: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile (P95 of 5 runs is the slowest run)."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize(seconds: List[float], failures: List[str], target: float) -> Dict:
    runs = len(seconds) + len(failures)
    p95 = percentile(seconds, 95)
    return {
        "runs": runs, "ok": len(seconds), "failed": len(failures),
        "success_rate": round(len(seconds) / runs, 3) if runs else None,
        "avg_s": round(statistics.mean(seconds), 2) if seconds else None,
        "median_s": round(statistics.median(seconds), 2) if seconds else None,
        "p95_s": round(p95, 2) if p95 is not None else None,
        "min_s": round(min(seconds), 2) if seconds else None,
        "max_s": round(max(seconds), 2) if seconds else None,
        "meets_target": bool(seconds) and not failures and p95 is not None and p95 < target,
        "errors": sorted(set(failures))[:5],
    }


def _targets(providers: Optional[List[str]]) -> List[Dict]:
    """One entry per provider model, with the credential the app would use."""
    out = []
    names = providers or ["local", "cloudflare", "huggingface", "together", "gemini", "pollinations", "aihorde"]
    for name in names:
        credentials = ig._credentials(name)
        if name == "cloudflare":
            for model in ig._cloudflare_models():
                out.append({"provider": name, "model": model, "credential": credentials[0] if credentials else None,
                            "env": {"CLOUDFLARE_IMAGE_MODELS": model}})
        elif name == "huggingface":
            models = ig._csv("HUGGINGFACE_IMAGE_MODELS", "HUGGINGFACE_IMAGE_MODEL") or [ig._DEFAULT_HUGGINGFACE_MODEL, "stabilityai/stable-diffusion-xl-base-1.0"]
            for model in models:
                out.append({"provider": name, "model": model, "credential": credentials[0] if credentials else None,
                            "env": {"HUGGINGFACE_IMAGE_MODELS": model}})
        else:
            model = {"together": os.getenv("TOGETHER_IMAGE_MODEL", "black-forest-labs/FLUX.1-schnell-Free"),
                     "gemini": os.getenv("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"),
                     "pollinations": os.getenv("POLLINATIONS_MODEL", "flux"),
                     "aihorde": "community Stable Diffusion workers",
                     "local": os.getenv("LOCAL_IMAGE_MODEL") or os.getenv("LOCAL_IMAGE_API", "openai")}.get(name, name)
            out.append({"provider": name, "model": model, "credential": credentials[0] if credentials else None, "env": {}})
    return out


def run_one(target: Dict, image_format: str, prompt: str, out_dir: Path, index: int, product=None):
    previous = {k: os.environ.get(k) for k in target["env"]}
    os.environ.update(target["env"])
    try:
        started = time.monotonic()
        raw = ig._PROVIDERS[target["provider"]](
            prompt, credential=target["credential"], size=ig.request_size(image_format), seed=1000 + index,
        )
        seconds = time.monotonic() - started
        raw = ig.verify_image(raw)
        returned = (raw.width, raw.height)
        image = ig.fit_to_format(raw, image_format)
        if product is not None:  # the real product photo, composited here (never sent)
            from PIL import Image
            import io as _io
            from src.ai.marketing import product_composite
            picture = product_composite.composite(Image.open(_io.BytesIO(image.content)), product, image_format)
            image.content, image.content_type = product_composite.to_bytes(picture)
            image.width, image.height = picture.size
    finally:
        for k, v in previous.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(image.content_type, "png")
    safe = f"{target['provider']}-{target['model']}".replace("/", "_").replace("@", "").replace(" ", "_")
    path = out_dir / f"{safe}-{image_format.lower()}{'-real-product' if product is not None else ''}-{index + 1}.{ext}"
    path.write_bytes(image.content)
    return seconds, returned, (image.width, image.height), image.content_type, path.name


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--formats", default="SQUARE,STORY")
    parser.add_argument("--providers", default="")
    parser.add_argument("--target", type=float, default=15.0)
    parser.add_argument("--out", default="benchmark-images")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--keyless", action="store_true",
                        help="also run Pollinations without a key (its free tier stamps a small logo on images)")
    parser.add_argument("--scene-product", default="",
                        help="a product photo (synthetic for tests): also make a real-product picture per run "
                             "(scene from the model + the photo composited here; the photo is never sent)")
    args = parser.parse_args(argv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = [f.strip().upper() for f in args.formats.split(",") if f.strip()]
    providers = [p.strip().lower() for p in args.providers.split(",") if p.strip()] or None
    rows = []
    product, product_name = None, "Extra virgin olive oil, 1 litre glass bottle"
    if args.scene_product:
        from src.ai.marketing import product_composite
        product, how = product_composite.cutout(Path(args.scene_product).read_bytes())
        print(f"product photo cut out locally ({how}); it is never sent to a provider", flush=True)
    for target in _targets(providers):
        row = {"provider": target["provider"], "model": target["model"],
               "pictures_per_request": PICTURES_PER_REQUEST.get(target["provider"], "1"), "formats": {}}
        if target["credential"] is None and args.keyless and target["provider"] == "pollinations":
            target["keyless"] = True
        if target["credential"] is None and not target.get("keyless"):
            row["skipped"] = "no credentials configured (the app could not use it either)"
            rows.append(row)
            print(f"SKIP {target['provider']} {target['model']}: {row['skipped']}", flush=True)
            continue
        jobs = [(f, None) for f in formats] + ([(f, product) for f in formats] if product is not None else [])
        for image_format, with_product in jobs:
            label = f"{image_format}+real-product" if with_product is not None else image_format
            seconds, failures, sizes, kinds, files = [], [], set(), set(), []
            if with_product is not None:  # exactly what the app sends for a real-product picture
                prompt = ig.shape_prompt(product_composite.scene_prompt(product_name, args.prompt), image_format, scene=True)
            else:
                prompt = ig.shape_prompt(args.prompt, image_format)  # exactly what the app sends
            for index in range(args.runs):
                try:
                    took, returned, kept, kind, name = run_one(target, image_format, prompt, out_dir, index, with_product)
                    seconds.append(took)
                    sizes.add(f"{returned[0]}x{returned[1]} -> {kept[0]}x{kept[1]}")
                    kinds.add(kind)
                    files.append(name)
                    print(f"  {target['provider']:12} {target['model'][:44]:44} {label:22} run {index + 1}: {took:6.2f}s", flush=True)
                except ig.ImageGenerationError as err:
                    failures.append(err.message[:160])
                    print(f"  {target['provider']:12} {target['model'][:44]:44} {label:22} run {index + 1}: FAILED {err.message[:100]}", flush=True)
                    if err.status == "NOT_CONFIGURED" or "rate limit" in err.message or "allowance" in err.message:
                        break  # no point repeating a refusal
            row["formats"][label] = {**summarize(seconds, failures, args.target),
                                            "sizes": sorted(sizes), "content_types": sorted(kinds), "files": files}
        rows.append(row)

    report = {"target_seconds": args.target, "runs_per_format": args.runs, "formats": formats,
              "prompt": args.prompt, "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": rows}
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    lines = [f"# Image model benchmark ({report['measured_at']})", "",
             f"{args.runs} real requests per model and format; target: P95 under {args.target:g} s.", "",
             "| Provider | Model | Format | OK / runs | Avg s | Median s | P95 s | Returned -> kept | Meets target |",
             "|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        if row.get("skipped"):
            lines.append(f"| {row['provider']} | {row['model']} | - | SKIPPED: {row['skipped']} | | | | | |")
            continue
        for image_format, r in row["formats"].items():
            lines.append(f"| {row['provider']} | {row['model']} | {image_format} | {r['ok']} / {r['runs']} | {r['avg_s']} | "
                         f"{r['median_s']} | {r['p95_s']} | {'; '.join(r['sizes'])} | {'yes' if r['meets_target'] else 'no'} |")
            if r["errors"]:
                lines.append(f"| | | | errors: {'; '.join(r['errors'])} | | | | | |")
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())

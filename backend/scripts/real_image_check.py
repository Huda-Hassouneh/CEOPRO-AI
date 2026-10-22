"""
KEEL - end-to-end check of real image generation on a running stack.

Signs in as a company, creates a campaign (or uses --campaign), queues a
batch of every format x --variations through the API, waits for the image
worker, then checks each finished image the way a customer would get it:
listed in the campaign gallery, downloadable through the API, a valid image
of the format's exact ratio, and made by a model ("ai", not the designed
fallback). It also checks the pixels look like a photograph or illustration,
not a placeholder: a flat colour, a gradient or a stand-in picture fails
(colour spread, number of distinct colours and fine detail all have to pass).

    python -m scripts.real_image_check --api http://localhost:8000 \\
        --email owner@example.com --password '...' [--campaign <id>] \\
        [--variations 1] [--out ./real-images] [--timeout-minutes 120]

Writes every image and a JSON report (timings, sizes, statistics) to --out.
Exit status 0 only when every image passed.
"""
import argparse
import io
import json
import os
import sys
import time

import httpx
from PIL import Image, ImageFilter, ImageStat

RATIOS = {"SQUARE": 1.0, "PORTRAIT": 0.8, "STORY": 9 / 16, "LANDSCAPE": 16 / 9, "WIDE": 1.91}


def image_statistics(content: bytes) -> dict:
    with Image.open(io.BytesIO(content)) as picture:
        picture.load()
        rgb = picture.convert("RGB")
        small = rgb.resize((256, max(1, round(256 * rgb.height / rgb.width))))
        spread = sum(ImageStat.Stat(small).stddev) / 3
        colours = len(small.getcolors(maxcolors=small.width * small.height) or [])
        detail = ImageStat.Stat(small.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
        return {"width": rgb.width, "height": rgb.height, "format": picture.format, "colour_spread": round(spread, 1),
                "distinct_colours_256px": colours, "edge_detail": round(detail, 1)}


def looks_real(stats: dict) -> bool:
    """Thresholds measured on real SDXL output vs flat/gradient stand-ins:
    real photos here had spread 40-70, 20k+ colours, detail 8-20; a flat
    image has spread ~0 and a few colours; a smooth gradient has detail < 2."""
    return stats["colour_spread"] >= 15 and stats["distinct_colours_256px"] >= 3000 and stats["edge_detail"] >= 3


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--api", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--campaign")
    parser.add_argument("--variations", type=int, default=1)
    parser.add_argument("--formats", default=",".join(RATIOS))
    parser.add_argument("--prompt", help="the owner's image description (default: the campaign's own)")
    parser.add_argument("--out", default="./real-image-check")
    parser.add_argument("--timeout-minutes", type=float, default=120)
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    client = httpx.Client(base_url=args.api, timeout=600)
    token = client.post("/auth/login", json={"email": args.email, "password": args.password}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    campaign_id = args.campaign
    if not campaign_id:
        created = client.post("/marketing/campaigns", json={
            "text": "Za'atar spice mix, 250 g glass jar, roasted sesame and wild thyme, from a family bakery in Amman",
            "strategy_type": "SALES_DRIVEN", "platforms": ["INSTAGRAM"], "variants_per_platform": 1})
        if created.status_code != 200:
            print(f"FAIL: campaign could not be created ({created.status_code}): {created.text[:300]}")
            return 1
        campaign_id = created.json()["campaign_id"]
    print(f"campaign {campaign_id}")

    formats = [f for f in args.formats.split(",") if f]
    before = {a["asset_id"] for a in client.get(f"/marketing/campaigns/{campaign_id}/assets").json()["assets"]}
    queued = client.post(f"/marketing/campaigns/{campaign_id}/image-batches",
                         json={"formats": formats, "variations": args.variations, "prompt": args.prompt})
    if queued.status_code != 200:
        print(f"FAIL: batch not queued ({queued.status_code}): {queued.text[:300]}")
        return 1
    batch = queued.json()
    print(f"queued {batch['queued']} images (batch {batch['batch_id']}); capacity: {json.dumps(batch['capacity'])}")

    started, deadline = time.monotonic(), time.monotonic() + args.timeout_minutes * 60
    while time.monotonic() < deadline:
        progress = client.get(f"/marketing/campaigns/{campaign_id}/image-jobs", params={"batch_id": batch["batch_id"]}).json()
        counts = progress["counts"]
        print(f"  {time.monotonic() - started:6.0f}s  {counts}", flush=True)
        if counts["QUEUED"] + counts["RUNNING"] == 0:
            break
        time.sleep(20)
    else:
        print("FAIL: timed out waiting for the worker")
        return 1

    report, failures = {"campaign_id": campaign_id, "batch_id": batch["batch_id"], "images": []}, 0
    gallery = {a["asset_id"]: a for a in client.get(f"/marketing/campaigns/{campaign_id}/assets").json()["assets"]}
    for job in sorted(progress["jobs"], key=lambda j: j["created_at"]):
        entry = {"format": job["image_format"], "status": job["status"], "seconds": job["seconds"], "attempts": job["attempts"],
                 "error": job["error"]}
        problems = []
        if job["status"] != "COMPLETED":
            problems.append(f"job {job['status']}: {job['error']}")
        elif job["mode"] != "ai":
            problems.append(f"made by '{job['mode']}', not a model")
        asset = gallery.get(job["asset_id"]) if job["asset_id"] else None
        if job["status"] == "COMPLETED":
            if asset is None or job["asset_id"] in before:
                problems.append("not in the campaign gallery")
            download = client.get(f"/marketing/campaigns/{campaign_id}/assets/{job['asset_id']}/image")
            if download.status_code != 200:
                problems.append(f"download failed ({download.status_code})")
            else:
                stats = image_statistics(download.content)
                entry.update(stats, bytes=len(download.content))
                ratio = stats["width"] / stats["height"]
                if abs(ratio - RATIOS[job["image_format"]]) / RATIOS[job["image_format"]] > 0.02:
                    problems.append(f"ratio {ratio:.3f} is not {job['image_format']}")
                if not looks_real(stats):
                    problems.append(f"pixels look like a placeholder: {stats}")
                name = f"{len(report['images']) + 1:02d}_{job['image_format'].lower()}.{'jpg' if stats['format'] == 'JPEG' else 'png'}"
                with open(os.path.join(args.out, name), "wb") as handle:
                    handle.write(download.content)
                entry["file"] = name
        entry["problems"] = problems
        failures += bool(problems)
        report["images"].append(entry)
        print(f"{'PASS' if not problems else 'FAIL'} {job['image_format']:9} "
              f"{entry.get('width')}x{entry.get('height')} {job['seconds']}s {'; '.join(problems)}")
    report["wall_seconds"] = round(time.monotonic() - started, 1)
    with open(os.path.join(args.out, "report.json"), "w") as handle:
        json.dump(report, handle, indent=2)
    print(f"{len(report['images']) - failures}/{len(report['images'])} images passed in {report['wall_seconds']}s; "
          f"report: {os.path.join(args.out, 'report.json')}")
    return 0 if failures == 0 and report["images"] else 1


if __name__ == "__main__":
    sys.exit(main())

"""
KEEL Arabic marketing evaluation - automated checks + human rubric.

    python -m scripts.arabic_benchmark.marketing_eval --llm [--out DIR]

Generates each prompt in ground_truth.MARKETING_PROMPTS through KEEL's real
content_generator.generate_campaign_content() (same provider chain, prompt,
factual review and metering as the Marketing Studio). It makes hosted LLM
calls (2-4 per prompt), so it never runs without --llm.

Automated checks (objective, per variant):
- script: share of letters in Arabic script for language="ar" outputs;
- hashtags: every tag a single valid platform tag (#word_word);
- platform limits: Google Ads headline <= 30 / description <= 90 characters;
- fabricated facts: any price, discount, percentage or number that is not
  in the product facts; any origin/certification/health wording;
- presentation forms / bidi overrides (pre-shaped or reversed text).

Fluency, grammar, dialect accuracy, cultural fit, persuasiveness and brand
voice are NOT scored by a model here: the run writes rubric.csv for two
human reviewers (1-5 per criterion, definitions in RUBRIC) - an LLM grading
its own output is not an objective measurement.
"""
import argparse
import csv
import json
import os
import re
import time

from scripts.arabic_benchmark import ground_truth as gt

RUBRIC = {
    "grammar": "1 = frequent grammatical errors ... 5 = no errors (MSA or the requested dialect's own grammar)",
    "spelling": "1 = many misspellings/wrong hamza/taa marbuta ... 5 = none",
    "fluency": "1 = reads as a literal translation ... 5 = reads as written by a native copywriter",
    "dialect": "only when Jordanian/Levantine was requested: 1 = MSA or another dialect ... 5 = natural Levantine",
    "cultural_fit": "1 = inappropriate for a Jordanian audience ... 5 = fully appropriate",
    "persuasiveness": "1 = no reason to act ... 5 = compelling hook and CTA",
    "relevance": "1 = generic, not about this product ... 5 = specific to the supplied product",
    "brand_voice": "1 = ignores the requested tone ... 5 = matches it",
    "hashtags": "1 = irrelevant/invalid ... 5 = relevant, correctly formed, right count for the platform",
    "platform_format": "1 = wrong length/structure for the platform ... 5 = platform-native",
}
_ARABIC = re.compile(r"[؀-ۿ]")
_LATIN = re.compile(r"[A-Za-z]")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?%?")
_SENSITIVE = re.compile(r"organic|certified|award|cures?|clinically|عضوي|معتمد|شهادة|يعالج|يشفي|مصنوع في|معبأ في|خصم|تخفيض|discount|sale\b|% off", re.I)
_TAG = re.compile(r"^#[\wـ]+$")


def _checks(variant: dict, platform: str, language: str, facts: str) -> dict:
    text = " ".join(str(variant.get(k) or "") for k in ("headline", "body_copy", "cta"))
    letters = len(_ARABIC.findall(text)) + len(_LATIN.findall(text))
    facts_numbers = set(_NUMBER.findall(facts.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))))
    numbers = [n for n in _NUMBER.findall(text.translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))) if n not in facts_numbers]
    out = {
        "arabic_script_share": round(len(_ARABIC.findall(text)) / letters, 3) if letters else None,
        "invalid_hashtags": [t for t in variant.get("hashtags") or [] if not _TAG.match(t)],
        "unsupported_numbers": numbers,
        "sensitive_claim_words": sorted(set(m.group().lower() for m in _SENSITIVE.finditer(text + " " + " ".join(variant.get("hashtags") or [])))),
        "presentation_forms_or_overrides": bool(re.search(r"[ﭐ-﷿ﹰ-﻿‭‮]", text)),
    }
    if platform == "GOOGLE_ADS":
        out["google_ads_limits_ok"] = len(variant.get("headline") or "") <= 30 and len(variant.get("body_copy") or "") <= 90
    out["pass"] = (not out["invalid_hashtags"] and not out["unsupported_numbers"] and not out["sensitive_claim_words"]
                   and not out["presentation_forms_or_overrides"] and out.get("google_ads_limits_ok", True)
                   and (language != "ar" or (out["arabic_script_share"] or 0) >= 0.8))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="required: makes hosted LLM calls")
    parser.add_argument("--out", default="marketing-eval")
    args = parser.parse_args(argv)
    if not args.llm:
        parser.error("this evaluation calls the configured LLM provider; pass --llm to run it")
    from dataclasses import asdict

    from src.ai.marketing import content_generator

    os.makedirs(args.out, exist_ok=True)
    products = {p["id"]: p for p in gt.MARKETING_PRODUCTS}
    results, rubric_rows = [], []
    for prompt in gt.MARKETING_PROMPTS:
        facts = products[prompt["product"]]["facts"]
        started = time.perf_counter()
        try:
            campaign = content_generator.generate_campaign_content(
                facts, tone=prompt["tone"], strategy_type=prompt["strategy"], language=prompt["language"],
                platforms=prompt["platforms"], variants_per_platform=2)
            error = None
        except Exception as err:  # noqa: BLE001 - a refusal/failure is a result
            campaign, error = None, f"{type(err).__name__}: {err}"[:300]
        row = {"id": prompt["id"], "prompt": prompt, "seconds": round(time.perf_counter() - started, 2), "error": error}
        if campaign:
            row["output"] = asdict(campaign)
            row["checks"] = {platform: [_checks(asdict(v), platform, prompt["language"], facts) for v in variants]
                             for platform, variants in campaign.variants_by_platform.items()}
            for platform, variants in campaign.variants_by_platform.items():
                for n, variant in enumerate(variants):
                    rubric_rows.append({"id": prompt["id"], "platform": platform, "variant": n, "tone": prompt["tone"],
                                        "text": json.dumps(asdict(variant), ensure_ascii=False), **{k: "" for k in RUBRIC}})
        results.append(row)
    with open(os.path.join(args.out, "results.json"), "w", encoding="utf-8") as handle:
        json.dump({"rubric": RUBRIC, "results": results}, handle, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "rubric.csv"), "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["id", "platform", "variant", "tone", "text", *RUBRIC])
        writer.writeheader()
        writer.writerows(rubric_rows)
    checked = [c for r in results for v in (r.get("checks") or {}).values() for c in v]
    print(json.dumps({"prompts": len(results), "failed_generations": sum(1 for r in results if r["error"]),
                      "variants": len(checked), "automated_pass": sum(c["pass"] for c in checked)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

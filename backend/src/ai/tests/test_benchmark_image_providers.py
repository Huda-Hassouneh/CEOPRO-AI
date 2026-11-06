"""The image benchmark's statistics and its honest skipping (no real
provider is called here - the script itself is for real runs)."""
from scripts import benchmark_image_providers as bench


def test_nearest_rank_percentile_and_summary():
    assert bench.percentile([3.0, 1.0, 2.0, 5.0, 4.0], 95) == 5.0
    assert bench.percentile([], 95) is None
    summary = bench.summarize([2.0, 4.0, 3.0, 5.0, 6.0], [], target=15)
    assert summary == {"runs": 5, "ok": 5, "failed": 0, "success_rate": 1.0, "avg_s": 4.0, "median_s": 4.0,
                       "p95_s": 6.0, "min_s": 2.0, "max_s": 6.0, "meets_target": True, "errors": []}
    slow = bench.summarize([10.0, 16.0], ["HTTP 500"], target=15)
    assert slow["meets_target"] is False and slow["success_rate"] == 0.667 and slow["failed"] == 1


def test_a_provider_without_credentials_is_skipped_not_measured(tmp_path, monkeypatch, capsys):
    for name in ("CLOUDFLARE_ACCOUNTS", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "TOGETHER_API_KEYS"):
        monkeypatch.delenv(name, raising=False)
    assert bench.main(["--providers", "cloudflare,together", "--runs", "1", "--out", str(tmp_path)]) == 0
    report = (tmp_path / "report.md").read_text()
    assert report.count("SKIPPED") == 5  # four Cloudflare models + Together
    assert "flux-1-schnell" in report

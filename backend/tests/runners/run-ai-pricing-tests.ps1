param(
    [ValidateSet("All", "Contract", "GradioContract", "Deterministic", "Database", "TenantIsolation", "Entitlements", "Usage", "Concurrency", "Competitor", "FX", "Safeguards", "Evidence", "FastApi", "E2E", "LiveGradio", "Headed", "Single", "Report", "Previous")]
    [string]$Mode = "All",
    [string]$Grep = ""
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $repoRoot
try {
    $commands = @{
        Contract = @("run", "test:ai-pricing:contract")
        GradioContract = @("run", "test:ai-pricing:gradio-contract")
        Deterministic = @("run", "test:ai-pricing:deterministic")
        Database = @("run", "test:ai-pricing:database")
        TenantIsolation = @("run", "test:ai-pricing:database")
        Entitlements = @("exec", "--", "node", "--test", "--test-name-pattern=entitlement|plan", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        Usage = @("exec", "--", "node", "--test", "--test-name-pattern=usage|billing|allocation", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        Concurrency = @("exec", "--", "node", "--test", "--test-name-pattern=concurrent|idempotency|duplicate", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        Competitor = @("exec", "--", "node", "--test", "--test-name-pattern=competitor|observation", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        FX = @("exec", "--", "node", "--test", "--test-name-pattern=currency|FX|rate", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        Safeguards = @("run", "test:ai-pricing:deterministic")
        Evidence = @("exec", "--", "node", "--test", "--test-name-pattern=evidence|provenance|persistence", "tests/ai-pricing/ai-pricing-contract.test.mjs")
        FastApi = @("run", "test:ai-pricing:fastapi")
        E2E = @("run", "test:ai-pricing:e2e")
        LiveGradio = @("run", "test:ai-pricing:live-gradio")
        Headed = @("run", "test:ai-pricing:headed")
        Single = @("run", "test:ai-pricing:single")
        Report = @("run", "test:ai-pricing:report")
        Previous = @("run", "test:all-features")
    }

    $modes = if ($Mode -eq "All") { @("Contract", "GradioContract", "Deterministic", "Database", "E2E") } else { @($Mode) }
    $results = @()
    foreach ($selected in $modes) {
        Write-Host "`n=== AI Pricing: $selected ==="
        $args = $commands[$selected]
        if ($selected -eq "Single" -and $Grep) { $args += @("--", "--grep", $Grep) }
        & npm @args
        $code = $LASTEXITCODE
        $status = if ($code -eq 0) { "PASS" } elseif ($code -eq 2) { "BLOCKED" } else { "FAIL" }
        $results += [pscustomobject]@{ mode = $selected; status = $status; exitCode = $code }
    }

    $reportDir = Join-Path $repoRoot "tests/reports/ai-pricing"
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    [pscustomobject]@{ generatedAt = (Get-Date).ToUniversalTime().ToString("o"); suite = "Feature 15 AI Pricing"; tests = $results } |
        ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $reportDir "powershell-run-summary.json")
    if (@($results | Where-Object { $_.status -eq "FAIL" }).Count -gt 0) { exit 1 }
} finally {
    Pop-Location
}

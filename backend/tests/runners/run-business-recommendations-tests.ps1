param(
    [switch]$IncludeLiveAI
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $repoRoot
try {
    $suites = @(
        @{ Name = "Node catalog, plan, architecture"; Script = "test:business-recommendations:node-contract" },
        @{ Name = "AI deterministic calculations and source regressions"; Script = "test:business-recommendations:deterministic" },
        @{ Name = "Python AI/API unit suite"; Script = "test:business-recommendations:python" },
        @{ Name = "AI PostgreSQL integration and RLS"; Script = "test:business-recommendations:ai-db" },
        @{ Name = "Customer flow Playwright diagnostics"; Script = "test:business-recommendations:frontend" }
    )
    if ($IncludeLiveAI) {
        $suites += @{ Name = "Opt-in live AI endpoint contract"; Script = "test:business-recommendations:live-ai-api" }
    }

    $results = @()
    foreach ($suite in $suites) {
        Write-Host "`n=== $($suite.Name) ==="
        npm run $suite.Script
        $exitCode = $LASTEXITCODE
        $status = if ($exitCode -eq 0) { "PASS_OR_SKIPPED" } elseif ($exitCode -eq 2) { "BLOCKED_OR_UNAVAILABLE" } else { "FAIL" }
        $results += [pscustomobject]@{
            name = $suite.Name
            script = $suite.Script
            status = $status
            exitCode = $exitCode
        }
    }

    $reportDir = Join-Path $repoRoot "tests/reports/business-recommendations"
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    $summary = [pscustomobject]@{
        generatedAt = (Get-Date).ToUniversalTime().ToString("o")
        suite = "Business Recommendations"
        tests = $results
    }
    $summary | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $reportDir "powershell-run-summary.json")
    $failed = @($results | Where-Object { $_.status -eq "FAIL" })
    if ($failed.Count -gt 0) { exit 1 }
} finally {
    Pop-Location
}

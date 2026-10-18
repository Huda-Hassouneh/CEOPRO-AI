param(
    [ValidateSet("All", "Contract", "Deterministic", "Database", "E2E", "Headed", "Single", "Report")]
    [string]$Mode = "All"
)

$ErrorActionPreference = "Continue"
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location $repoRoot
try {
    $commands = @{
        Contract = "test:smart-alerts:contract"
        Deterministic = "test:smart-alerts:deterministic"
        Database = "test:smart-alerts:database"
        E2E = "test:smart-alerts:e2e"
        Headed = "test:smart-alerts:headed"
        Single = "test:smart-alerts:single"
        Report = "test:smart-alerts:report"
    }
    $modes = if ($Mode -eq "All") { @("Contract", "Deterministic", "Database", "E2E") } else { @($Mode) }
    $results = @()
    foreach ($selected in $modes) {
        Write-Host "`n=== Smart Alerts: $selected ==="
        npm run $commands[$selected]
        $code = $LASTEXITCODE
        $status = if ($code -eq 0) { "PASS" } elseif ($code -eq 2) { "BLOCKED" } else { "FAIL" }
        $results += [pscustomobject]@{ mode = $selected; script = $commands[$selected]; status = $status; exitCode = $code }
    }
    $reportDir = Join-Path $repoRoot "tests/reports/smart-alerts"
    New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
    [pscustomobject]@{ generatedAt = (Get-Date).ToUniversalTime().ToString("o"); suite = "Smart Alerts"; tests = $results } |
        ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8 (Join-Path $reportDir "powershell-run-summary.json")
    if (@($results | Where-Object { $_.status -eq "FAIL" }).Count -gt 0) { exit 1 }
} finally {
    Pop-Location
}

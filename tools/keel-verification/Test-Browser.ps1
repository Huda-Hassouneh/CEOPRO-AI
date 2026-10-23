param([switch]$IncludeDataImport, [switch]$IncludeNotifications)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$env:KEEL_VERIFICATION_STATE = $state
$fixturePath = Join-Path $state 'competitor-browser-fixture.json'
if (-not (Test-Path $fixturePath)) { throw 'Run Prepare-BrowserFixture.ps1 after starting FastAPI first.' }
$fixture = Get-Content $fixturePath -Raw | ConvertFrom-Json
$env:KEEL_VERIFY_FIXTURE = $fixturePath
$env:API_URL = 'http://127.0.0.1:8000'
$env:APP_URL = 'http://127.0.0.1:5178'
$env:CHROMIUM_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
foreach ($url in @("$($env:API_URL)/health/ready", $env:APP_URL)) {
  $status = & curl.exe --silent --show-error --output NUL --write-out '%{http_code}' --max-time 3 $url 2>$null
  if ($status -ne '200') { throw "Required local server is not ready at $url. Start the persistent test backend and frontend first." }
}
Push-Location (Join-Path $repo 'frontend')
try {
  foreach ($locale in @('en', 'ar')) {
    $env:E2E_LOCALE = $locale
    node tests/browser/competitor-workflow.mjs
    if ($LASTEXITCODE -ne 0) { throw "Competitor browser workflow failed for $locale." }
  }
  if ($IncludeDataImport) {
    & (Join-Path $PSScriptRoot 'Prepare-ImportFixture.ps1')
    $importPath = Join-Path $state 'import-browser-fixture.json'
    $import = Get-Content $importPath -Raw | ConvertFrom-Json
    $env:E2E_EMAIL = $import.email
    $env:E2E_PASSWORD = $import.password
    $env:E2E_OTHER_TENANT_TOKEN = $import.other_token
    $env:E2E_VALID_MARKER = $import.valid
    $env:E2E_RETRY_MARKER = $import.retry
    $env:E2E_CORRECTED_MARKER = $import.corrected
    $env:E2E_ARABIC_MARKER = $import.arabic
    $env:E2E_INVALID_MARKER = $import.invalid
    foreach ($locale in @('en', 'ar')) {
      $env:E2E_LOCALE = $locale
      node tests/browser/data-import.mjs
      if ($LASTEXITCODE -ne 0) { throw "CSV import-to-Dashboard browser workflow failed for $locale." }
    }
  }
  if ($IncludeNotifications) {
    if (-not (Test-Path -LiteralPath (Join-Path $state 'import-browser-fixture.json'))) {
      & (Join-Path $PSScriptRoot 'Prepare-ImportFixture.ps1')
    }
    try {
      foreach ($locale in @('en', 'ar')) {
        & (Join-Path $PSScriptRoot 'Prepare-NotificationFixture.ps1')
        $env:E2E_LOCALE = $locale
        node tests/browser/notifications-workflow.mjs
        if ($LASTEXITCODE -ne 0) { throw "Notification browser workflow failed for $locale." }
      }
    } finally {
      $values = @{}
      Get-Content (Join-Path $state 'compose.env') | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2] } }
      $env:DATABASE_URL = "postgresql://keel_verify_admin:$($values['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/keel_verification"
      $env:KEEL_VERIFICATION_STATE = $state
      $python = Join-Path $state 'python-venv/Scripts/python.exe'
      Push-Location (Join-Path $repo 'backend')
      try { & $python scripts/seed_notification_browser_fixture.py --cleanup } finally { Pop-Location }
    }
  }
} finally { Pop-Location }

param()
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$fixturePath = Join-Path $state 'competitor-browser-fixture.json'
if (-not (Test-Path -LiteralPath $fixturePath)) { throw 'Run Prepare-BrowserFixture.ps1 after starting FastAPI first.' }
foreach ($url in @('http://127.0.0.1:8000/health/ready', 'http://127.0.0.1:5178')) {
  $status = & curl.exe --silent --show-error --output NUL --write-out '%{http_code}' --max-time 3 $url 2>$null
  if ($status -ne '200') { throw "Start the current verification FastAPI/Vite services first: $url" }
}
$fixture = Get-Content -LiteralPath $fixturePath -Raw | ConvertFrom-Json
$env:KEEL_VERIFY_FIXTURE = $fixturePath
$env:APP_URL = 'http://127.0.0.1:5178'
$env:API_URL = 'http://127.0.0.1:8000'
$env:CHROMIUM_PATH = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$script = Join-Path $repo 'frontend/tests/browser/phase7-provider-setup-smoke.mjs'
Push-Location (Join-Path $repo 'frontend')
try {
  node $script
  if ($LASTEXITCODE -ne 0) { throw 'Phase 7 provider setup browser smoke failed.' }
} finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$values = @{}
Get-Content (Join-Path $state 'compose.env') | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2] } }
$env:DATABASE_URL = "postgresql://keel_verify_admin:$($values['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/keel_verification"
$env:APP_DB_PASSWORD = $values['KEEL_VERIFY_APP_PASSWORD']
$env:PYTHONPATH = Join-Path $repo 'backend'
$env:JWT_SECRET = 'local-only-keel-verification-secret-change-me'
$env:CREDENTIAL_VAULT_MASTER_KEY = [Convert]::ToBase64String([byte[]](1..32))
$env:KEEL_VERIFICATION_STATE = $state
$python = Join-Path $state 'python-venv/Scripts/python.exe'
Push-Location (Join-Path $repo 'backend')
try {
  & $python scripts/seed_competitor_browser_fixture.py
  if ($LASTEXITCODE -ne 0) { throw 'Could not prepare browser fixture.' }
} finally { Pop-Location }
$fixture = Join-Path $state 'competitor-browser-fixture.json'
icacls $fixture /inheritance:r /grant:r "$env:USERNAME`:(R,W)" 'NT AUTHORITY\SYSTEM:(R,W)' | Out-Null
Write-Output "Synthetic fixture stored outside Git at $fixture; credential values were not printed."

param([Parameter(ValueFromRemainingArguments=$true)][string[]]$PytestArgs)
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$envFile = Join-Path $state 'compose.env'
if (-not (Test-Path -LiteralPath $envFile)) { throw 'Run Initialize.ps1 first.' }
$values = @{}
Get-Content $envFile | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2] } }
$env:DATABASE_URL = "postgresql://keel_verify_admin:$($values['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/keel_verification"
$env:AI_TEST_DATABASE_URL = $env:DATABASE_URL
$env:APP_DB_PASSWORD = $values['KEEL_VERIFY_APP_PASSWORD']
$env:SCRAPER_DATABASE_URL = "postgresql://ceopro_app:$($values['KEEL_VERIFY_APP_PASSWORD'])@127.0.0.1:55446/keel_verification"
$env:SCRAPER_ACTOR_USER_ID = '00000000-0000-0000-0000-000000000000'
$env:AI_SERVICE_ACTOR_USER_ID = '00000000-0000-0000-0000-000000000000'
$env:REDIS_URL = 'redis://127.0.0.1:56340/0'
$env:MINIO_ENDPOINT = '127.0.0.1:59002'
$env:MINIO_ROOT_USER = $values['KEEL_VERIFY_MINIO_USER']
$env:MINIO_ROOT_PASSWORD = $values['KEEL_VERIFY_MINIO_PASSWORD']
$env:MINIO_SECURE = 'false'
$env:JWT_SECRET = 'local-only-keel-verification-secret-change-me'
$vaultBytes = New-Object byte[] 32
$vaultRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$vaultRng.GetBytes($vaultBytes)
$env:CREDENTIAL_VAULT_MASTER_KEY = [Convert]::ToBase64String($vaultBytes)
$vaultRng.Dispose()
$env:PYTHONPATH = Join-Path $repo 'backend'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$python = Join-Path $state 'python-venv/Scripts/python.exe'
Push-Location (Join-Path $repo 'backend')
try { & $python -m pytest @PytestArgs; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } } finally { Pop-Location }

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$values = @{}
Get-Content (Join-Path $state 'compose.env') | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2] } }
$env:DATABASE_URL = "postgresql://keel_verify_admin:$($values['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/keel_verification"
$env:APP_DB_PASSWORD = $values['KEEL_VERIFY_APP_PASSWORD']
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
$env:DISCOVERY_REFRESH_ENABLED = 'false'
$env:NOTIFICATION_DIGEST_ENABLED = 'false'
$env:BILLING_MAINTENANCE_ENABLED = 'false'
$env:API_RATE_LIMIT_ENABLED = 'false'
$env:CORS_ALLOWED_ORIGINS = if ($env:KEEL_VERIFY_CORS_ORIGINS) { $env:KEEL_VERIFY_CORS_ORIGINS } else { 'http://127.0.0.1:5178,http://localhost:5178' }
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$python = Join-Path $state 'python-venv/Scripts/python.exe'
Push-Location (Join-Path $repo 'backend')
try { & $python -m uvicorn src.ai.main:app --host 127.0.0.1 --port 8000 } finally { Pop-Location }

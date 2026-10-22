$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
New-Item -ItemType Directory -Path $state -Force | Out-Null
$envFile = Join-Path $state 'compose.env'
if (-not (Test-Path -LiteralPath $envFile)) {
  $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
  function New-HexSecret($Bytes = 32) {
    $buffer = New-Object byte[] $Bytes
    $rng.GetBytes($buffer)
    return ([BitConverter]::ToString($buffer) -replace '-', '')
  }
  @(
    "KEEL_VERIFY_ADMIN_PASSWORD=$(New-HexSecret)"
    "KEEL_VERIFY_APP_PASSWORD=$(New-HexSecret)"
    "KEEL_VERIFY_MINIO_USER=keelverify"
    "KEEL_VERIFY_MINIO_PASSWORD=$(New-HexSecret)"
  ) | Set-Content -LiteralPath $envFile -Encoding ascii
  $rng.Dispose()
  # Keep the synthetic local credentials readable only by the current Windows user and SYSTEM.
  icacls $envFile /inheritance:r /grant:r "$env:USERNAME`:(R,W)" "NT AUTHORITY\SYSTEM:(R,W)" | Out-Null
}
$envValues = @{}
Get-Content -LiteralPath $envFile | ForEach-Object {
  if ($_ -match '^([^=]+)=(.*)$') { $envValues[$matches[1]] = $matches[2] }
}
$compose = Join-Path $PSScriptRoot 'compose.yaml'
& docker compose --project-name keel-verification --env-file $envFile -f $compose up -d
if ($LASTEXITCODE -ne 0) { throw 'Could not start the KEEL verification services.' }
$deadline = (Get-Date).AddMinutes(2)
do {
  $healthy = docker inspect --format '{{.State.Health.Status}}' keel-verification-postgres 2>$null
  if ($healthy -eq 'healthy') { break }
  Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if ($healthy -ne 'healthy') { throw 'Disposable verification PostgreSQL did not become healthy.' }
$venv = Join-Path $state 'python-venv'
if (-not (Test-Path (Join-Path $venv 'Scripts/python.exe'))) {
  & python -m venv --system-site-packages $venv
  if ($LASTEXITCODE -ne 0) { throw 'Could not create reusable verification venv.' }
}
$python = Join-Path $venv 'Scripts/python.exe'
$env:DATABASE_URL = "postgresql://keel_verify_admin:$($envValues['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/keel_verification"
$env:AI_TEST_DATABASE_URL = $env:DATABASE_URL
$env:APP_DB_PASSWORD = $envValues['KEEL_VERIFY_APP_PASSWORD']
$env:REDIS_URL = 'redis://127.0.0.1:56340/0'
$env:MINIO_ENDPOINT = '127.0.0.1:59002'
$env:MINIO_ROOT_USER = $envValues['KEEL_VERIFY_MINIO_USER']
$env:MINIO_ROOT_PASSWORD = $envValues['KEEL_VERIFY_MINIO_PASSWORD']
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
$env:KEEL_VERIFICATION_STATE = $state
Write-Output 'Reusable KEEL verification services are healthy. Synthetic credentials are process-scoped; values were not printed.'
Write-Output "Python environment: $venv"
Write-Output "Database endpoint: 127.0.0.1:55446/keel_verification"
Write-Output "Redis endpoint: 127.0.0.1:56340"
Write-Output "MinIO endpoint: 127.0.0.1:59002"

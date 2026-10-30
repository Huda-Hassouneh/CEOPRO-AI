$ErrorActionPreference = 'Stop'
$compose = Join-Path $PSScriptRoot 'compose.yaml'
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$envFile = Join-Path $state 'compose.env'
if (-not (Test-Path -LiteralPath $envFile)) { Write-Output 'Verification environment is not initialized.'; exit 0 }
& docker compose --project-name keel-verification --env-file $envFile -f $compose stop
if ($LASTEXITCODE -ne 0) { throw 'Could not stop the KEEL verification services.' }
Write-Output 'Verification containers stopped. Named PostgreSQL/MinIO volumes and the reusable Python environment were preserved.'

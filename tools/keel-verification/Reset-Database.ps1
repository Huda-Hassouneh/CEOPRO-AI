$ErrorActionPreference = 'Stop'
$admin = 'keel_verify_admin'
$db = 'keel_verification'
$container = docker ps --filter 'name=^/keel-verification-postgres$' --format '{{.Names}}'
if ($container -ne 'keel-verification-postgres') { throw 'Refusing reset: dedicated keel-verification-postgres container is not running.' }
# This drops only the explicitly named verification database in the dedicated verification container.
$terminate = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db' AND pid<>pg_backend_pid();"
docker exec keel-verification-postgres psql -v ON_ERROR_STOP=1 -U $admin -d postgres -c $terminate | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not terminate verification database sessions.' }
docker exec keel-verification-postgres dropdb --if-exists -U $admin $db
if ($LASTEXITCODE -ne 0) { throw 'Could not drop the dedicated verification database.' }
# ceopro_app is cluster-wide but this container is dedicated to KEEL verification.
docker exec keel-verification-postgres psql -v ON_ERROR_STOP=1 -U $admin -d postgres -c 'DROP ROLE IF EXISTS ceopro_app;' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not reset the dedicated restricted application role.' }
docker exec keel-verification-postgres createdb -U $admin -O $admin $db
if ($LASTEXITCODE -ne 0) { throw 'Could not recreate the dedicated verification database.' }
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$envFile = Join-Path $state 'compose.env'
$values = @{}
Get-Content $envFile | ForEach-Object { if ($_ -match '^([^=]+)=(.*)$') { $values[$matches[1]]=$matches[2] } }
$env:DATABASE_URL = "postgresql://$admin`:$($values['KEEL_VERIFY_ADMIN_PASSWORD'])@127.0.0.1:55446/$db"
$env:APP_DB_PASSWORD = $values['KEEL_VERIFY_APP_PASSWORD']
$python = Join-Path $state 'python-venv/Scripts/python.exe'
$env:PYTHONPATH = Join-Path (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path 'backend'
$oldErrorAction = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
& $python (Join-Path $env:PYTHONPATH 'scripts/apply_migrations.py') 2>&1 | ForEach-Object { Write-Host $_ }
$migrationExit = $LASTEXITCODE
$ErrorActionPreference = $oldErrorAction
if ($migrationExit -ne 0) { throw 'Fresh migrations failed on the disposable verification database.' }
Write-Output 'Dedicated verification database reset and migrations applied. No other database was touched.'

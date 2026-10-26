# Root-relative Windows entry point. Arguments are passed without evaluating shell text.
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.dev/venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    $runtime = (Get-Command python -ErrorAction Stop).Source
}
# Windows PowerShell 5.1 must not turn native stderr into a terminating exception.
$ErrorActionPreference = 'Continue'
$global:LASTEXITCODE = 1
& $runtime (Join-Path $PSScriptRoot 'tools/dev/dev.py') @args 2>&1 | ForEach-Object { $_.ToString() }
exit $global:LASTEXITCODE

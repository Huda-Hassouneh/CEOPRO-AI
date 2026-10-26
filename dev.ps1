# Root-relative Windows entry point. Arguments are passed without evaluating shell text.
$ErrorActionPreference = 'Stop'
$runtime = Join-Path $PSScriptRoot '.dev/venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    $runtime = (Get-Command python -ErrorAction Stop).Source
}
& $runtime (Join-Path $PSScriptRoot 'tools/dev/dev.py') @args
exit $LASTEXITCODE

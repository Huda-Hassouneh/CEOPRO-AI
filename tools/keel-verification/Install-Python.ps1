$ErrorActionPreference = 'Stop'
$state = Join-Path $env:LOCALAPPDATA 'KEEL/verification'
$python = Join-Path $state 'python-venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run Initialize.ps1 first to create the reusable venv.' }
# Intentional focused runtime/test dependencies; respect declared project ranges and do not install torch/transformers/model weights.
$packages = @(
  'pytest>=9,<10', 'psycopg2-binary>=2.9,<3', 'redis>=5,<6', 'minio>=7.2,<8',
  'Scrapy>=2.11,<3', 'scrapy-playwright>=0.0.41,<1', 'extruct>=0.18,<1', 'prometheus-client>=0.20,<1',
  'pandas>=2,<3', 'xgboost>=2,<3', 'scikit-learn>=1.3,<2', 'pyarrow==23.0.1', 'rank-bm25>=0.2,<0.3',
  'uvicorn>=0.29,<1', 'python-multipart>=0.0.9,<0.1', 'PyJWT>=2.8,<3', 'stripe',
  'pdfplumber>=0.11,<0.12', 'openpyxl>=3.1,<4', 'python-docx>=1.1,<2', 'pytz>=2023.3',
  'python-bidi>=0.6,<1', 'sentry-sdk[fastapi]>=2.20,<3', 'boto3>=1.34,<2', 'Pillow>=13,<14'
)
& $python -m pip install --disable-pip-version-check $packages
if ($LASTEXITCODE -ne 0) { throw 'Focused Python dependency installation failed.' }
Write-Output "Declared-range Python test/runtime packages installed at $state. Heavy model packages and weights were not installed."

# Pass CLI flags unchanged, e.g. ./catalog_tool/catalog.ps1 search --query '耳机'.
$ErrorActionPreference = 'Stop'
$python = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Bundled Python not found. Run python catalog_tool/catalog.py with Python 3.11+ and openpyxl installed.'
}
$env:PYTHONIOENCODING = 'utf-8'
& $python (Join-Path $PSScriptRoot 'catalog.py') @args
if ($LASTEXITCODE -ne 0) { throw 'Catalogue command failed; see the JSON error above.' }

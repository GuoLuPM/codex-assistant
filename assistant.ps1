# No param block: forward capability CLI flags unchanged.
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'scripts\environment.ps1')
$assistantPython = Resolve-AssistantPython $PSScriptRoot
$env:PYTHONIOENCODING = 'utf-8'
& $assistantPython (Join-Path $PSScriptRoot 'assistant.py') @args
if ($LASTEXITCODE -ne 0) { throw "Assistant command failed with exit code $LASTEXITCODE; see the error above." }

# No param block: forward capability CLI flags unchanged.
$ErrorActionPreference = 'Stop'
if ($env:ASSISTANT_PYTHON) {
    $assistantPython = $env:ASSISTANT_PYTHON
    if (-not (Test-Path -LiteralPath $assistantPython -PathType Leaf)) {
        throw 'ASSISTANT_PYTHON must point to an existing Python executable.'
    }
} else {
    $runtimeRoot = $env:ASSISTANT_RUNTIME_ROOT
    if (-not $runtimeRoot) {
        $runtimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
    }
    $assistantPython = Join-Path $runtimeRoot 'python\python.exe'
    if (-not (Test-Path -LiteralPath $assistantPython -PathType Leaf)) {
        if ($env:ASSISTANT_RUNTIME_ROOT) { throw 'ASSISTANT_RUNTIME_ROOT has no python\python.exe.' }
        $pythonCommand = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pythonCommand) { throw 'Python unavailable. Set ASSISTANT_PYTHON; see docs/WINDOWS_SETUP.md.' }
        $assistantPython = $pythonCommand.Source
    }
}
$env:PYTHONIOENCODING = 'utf-8'
& $assistantPython (Join-Path $PSScriptRoot 'assistant.py') @args
if ($LASTEXITCODE -ne 0) { throw "Assistant command failed with exit code $LASTEXITCODE; see the error above." }

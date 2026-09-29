function Read-AssistantEnvironment([string]$ProjectRoot) {
    $configPath = Join-Path $ProjectRoot 'environment.local.json'
    if (-not (Test-Path -LiteralPath $configPath)) { return @{} }
    $config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($config.version -ne 1) { throw 'Unsupported environment.local.json version.' }
    $result = @{}
    foreach ($key in @('python', 'runtime_root', 'presentations_skill')) {
        if ($config.$key) { $result[$key] = [string]$config.$key }
    }
    return $result
}

function Resolve-AssistantPython([string]$ProjectRoot) {
    $config = Read-AssistantEnvironment $ProjectRoot
    $explicitPython = $env:ASSISTANT_PYTHON
    if (-not $explicitPython) { $explicitPython = $config['python'] }
    if ($explicitPython) {
        if (-not [IO.Path]::IsPathRooted($explicitPython) -or -not (Test-Path -LiteralPath $explicitPython -PathType Leaf)) {
            throw 'Configured Python must be an existing absolute executable path.'
        }
        return $explicitPython
    }
    $root = $env:ASSISTANT_RUNTIME_ROOT
    if (-not $root) { $root = $config['runtime_root'] }
    if (-not $root) { $root = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies' }
    $candidate = Join-Path $root 'python\python.exe'
    if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    if ($env:ASSISTANT_RUNTIME_ROOT -or $config['runtime_root']) { throw 'Selected runtime has no python\python.exe.' }
    $command = Get-Command python -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $command) { throw 'Python unavailable. Use the Windows release bundle; see docs/WINDOWS_SETUP.md.' }
    return $command.Source
}

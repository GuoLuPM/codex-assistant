[CmdletBinding()]
param(
    [string]$ProjectDir = 'D:\code\assistant',
    [string]$RuntimeDir = 'D:\tools\codex-assistant',
    [string]$Proxy,
    [string]$RuntimeRoot,
    [string]$SkillDir,
    [switch]$SkipPdf
)
$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'bundle.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($manifest.version -ne 1 -or $manifest.platform -ne 'windows-x64') { throw 'Unsupported bundle.' }
foreach ($required in @('runtime/python/python.exe', 'application/scripts/install_windows.py', 'Setup.ps1')) {
    if ($required -notin $manifest.files.PSObject.Properties.Name) { throw "Missing manifest entry: $required" }
}
# Verify payloads before launching the packaged executable.
foreach ($entry in $manifest.files.PSObject.Properties) {
    $path = [IO.Path]::GetFullPath((Join-Path $bundleRoot $entry.Name))
    if (-not $path.StartsWith($bundleRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe bundle path.' }
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing payload: $($entry.Name)" }
    $checkedPath = $path
    while ($checkedPath.Length -ge $bundleRoot.Length) {
        if ((Get-Item -LiteralPath $checkedPath -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Bundle cannot contain links.' }
        $checkedPath = Split-Path -Path $checkedPath -Parent
    }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $entry.Value) { throw "Payload hash mismatch: $($entry.Name)" }
}
$actualFiles = @(Get-ChildItem -LiteralPath $bundleRoot -Recurse -File -Force | Where-Object { $_.FullName -ne (Join-Path $bundleRoot 'bundle.json') })
if ($actualFiles.Count -ne @($manifest.files.PSObject.Properties).Count) { throw 'Bundle contains undeclared files.' }
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$installerArgs = @('--bundle', $bundleRoot, '--project-dir', $ProjectDir, '--runtime-dir', $RuntimeDir)
if ($Proxy) { $installerArgs += @('--proxy', $Proxy) }
if ($RuntimeRoot) { $installerArgs += @('--runtime-root', $RuntimeRoot) }
if ($SkillDir) { $installerArgs += @('--skill-dir', $SkillDir) }
if ($SkipPdf) { $installerArgs += '--skip-pdf' }
& (Join-Path $bundleRoot 'runtime\python\python.exe') -B (Join-Path $bundleRoot 'application\scripts\install_windows.py') @installerArgs
if ($LASTEXITCODE -ne 0) { throw 'Installation incomplete. Inspect the reported capability and rerun after resolving it.' }

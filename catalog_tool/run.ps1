[CmdletBinding(DefaultParameterSetName = 'Source')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Source')][string]$InputFile,
    [Parameter(Mandatory = $true, ParameterSetName = 'Selection')][string[]]$ProductIds,
    [string]$OutputFile,
    [string]$ConfigFile,
    [string]$CatalogConfigFile,
    [string]$IndexDir = (Join-Path $PSScriptRoot '..\.catalog-index'),
    [string[]]$PriceFields,
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'),
    [string]$SkillDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
if ($InputFile) { $source = (Resolve-Path -LiteralPath $InputFile).Path }
if (-not $ConfigFile) {
    $ConfigFile = Join-Path $projectRoot 'style.local.json'
    if (-not (Test-Path -LiteralPath $ConfigFile)) { $ConfigFile = Join-Path $PSScriptRoot 'style.json' }
}
$config = (Resolve-Path -LiteralPath $ConfigFile).Path
if (-not $OutputFile) {
    $OutputFile = Join-Path $projectRoot 'outputs\产品图册.pptx'
}
$output = [System.IO.Path]::GetFullPath($OutputFile)
if (-not $output.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputFile must be inside the project directory.'
}
$node = Join-Path $RuntimeRoot 'node\bin\node.exe'
$python = Join-Path $RuntimeRoot 'python\python.exe'
$modules = Join-Path $RuntimeRoot 'node\node_modules'
$bin = Join-Path $RuntimeRoot 'bin\override'
foreach ($required in @($node, $python, $modules)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Missing runtime dependency: $required" }
}
if (-not $SkillDir) {
    $skillBase = Join-Path $env:USERPROFILE '.codex\plugins\cache\openai-primary-runtime\presentations'
    $skillVersion = Get-ChildItem -LiteralPath $skillBase -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $skillVersion) { throw 'Presentation skill not found.' }
    $SkillDir = Join-Path $skillVersion.FullName 'skills\presentations'
}
if (-not (Test-Path -LiteralPath (Join-Path $SkillDir 'container_tools\artifact_tool_utils.mjs'))) {
    throw "Invalid presentation skill directory: $SkillDir"
}
$moduleLink = Join-Path $PSScriptRoot 'node_modules'
if (-not (Test-Path -LiteralPath $moduleLink)) {
    New-Item -ItemType Junction -Path $moduleLink -Target $modules | Out-Null
}
$workDir = Join-Path $projectRoot ('.catalog-work\run-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $workDir -Force | Out-Null
$stagedOutput = Join-Path $workDir 'staged\validated.pptx'
$env:PYTHONIOENCODING = 'utf-8'
$env:RUNTIME_NODE_MODULES = $modules
$env:RUNTIME_NODE = $node
$env:RUNTIME_PYTHON = $python
$env:RUNTIME_BIN_DIR = $bin
$env:PRESENTATION_SKILL_DIR = $SkillDir
$catalogScript = Join-Path $PSScriptRoot 'catalog.py'
$catalogArgs = @('--index-dir', $IndexDir)
if ($CatalogConfigFile) { $catalogArgs += @('--config', $CatalogConfigFile) }
if ($InputFile) {
    & $python $catalogScript @catalogArgs index $source
    if ($LASTEXITCODE -ne 0) { throw 'Source indexing failed.' }
    $stageArgs = @('stage-source', '--input', $source, '--work-dir', $workDir)
} else {
    $stageArgs = @('stage', '--ids') + $ProductIds + @('--work-dir', $workDir)
}
if ($PriceFields) { $stageArgs += @('--price-fields') + $PriceFields }
& $python $catalogScript @catalogArgs @stageArgs
if ($LASTEXITCODE -ne 0) { throw 'Product selection or source verification failed.' }
& $node (Join-Path $PSScriptRoot 'build.mjs') --work-dir $workDir --output $stagedOutput --config $config --workspace-dir $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Presentation generation failed.' }
& $python (Join-Path $PSScriptRoot 'verify.py') --work-dir $workDir --output $stagedOutput
if ($LASTEXITCODE -ne 0) { throw 'Workbook to presentation verification failed.' }
$outputDir = Split-Path -Path $output -Parent
New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
if (Test-Path -LiteralPath $output) {
    $previousFile = Join-Path $workDir 'previous.pptx'
    [System.IO.File]::Replace($stagedOutput, $output, $previousFile)
} else {
    Move-Item -LiteralPath $stagedOutput -Destination $output
}
$resolvedWork = (Resolve-Path -LiteralPath $workDir).Path
$workRoot = (Resolve-Path -LiteralPath (Join-Path $projectRoot '.catalog-work')).Path.TrimEnd('\') + '\'
if (-not $resolvedWork.StartsWith($workRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Refusing to remove a work directory outside .catalog-work.'
}
$links = Get-ChildItem -LiteralPath $workDir -Recurse -Force | Where-Object {
    $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint
}
if ($links) { throw 'Refusing to remove a work directory that contains links.' }
Remove-Item -LiteralPath $workDir -Recurse -Force
Write-Output $output

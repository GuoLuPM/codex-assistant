[CmdletBinding(DefaultParameterSetName = 'Source')]
param(
    [Parameter(Mandatory = $true, ParameterSetName = 'Source')][string]$InputFile,
    [Parameter(Mandatory = $true, ParameterSetName = 'Selection')][string[]]$ProductIds,
    [string]$OutputFile,
    [string]$ConfigFile,
    [string]$CatalogConfigFile,
    [string]$CatalogScript = (Join-Path $PSScriptRoot 'catalog.py'),
    [Parameter(ParameterSetName = 'Source')][string]$ImportMap,
    [string]$IndexDir = (Join-Path $PSScriptRoot '..\.catalog-index'),
    [string[]]$PriceFields,
    [string]$RuntimeRoot = $env:ASSISTANT_RUNTIME_ROOT,
    [string]$SkillDir = $env:ASSISTANT_PRESENTATIONS_SKILL
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
. (Join-Path $projectRoot 'scripts\environment.ps1')
$environmentConfig = Read-AssistantEnvironment $projectRoot
if (-not $RuntimeRoot) { $RuntimeRoot = $environmentConfig['runtime_root'] }
if (-not $SkillDir) { $SkillDir = $environmentConfig['presentations_skill'] }
if (-not $RuntimeRoot) {
    $RuntimeRoot = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'
}
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
$existingModules = Get-Item -LiteralPath $moduleLink -Force -ErrorAction SilentlyContinue
if ($existingModules) {
    if (-not ($existingModules.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -or
        [System.IO.Path]::GetFullPath([string]$existingModules.Target) -ne [System.IO.Path]::GetFullPath($modules)) {
        throw 'node_modules does not point to the selected Codex runtime. Inspect and repair this local junction explicitly.'
    }
} else {
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
$catalogScript = (Resolve-Path -LiteralPath $CatalogScript).Path
$catalogArgs = @('--index-dir', $IndexDir)
if ($CatalogConfigFile) { $catalogArgs += @('--config', $CatalogConfigFile) }
if ($InputFile) {
    $indexArgs = @('index', $source)
    if ($ImportMap) { $indexArgs += @('--map', $ImportMap) }
    & $python $catalogScript @catalogArgs @indexArgs
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

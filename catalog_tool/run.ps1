param(
    [Parameter(Mandatory = $true)][string]$InputFile,
    [string]$OutputFile,
    [string]$ConfigFile = (Join-Path $PSScriptRoot 'sendem.json'),
    [string]$RuntimeRoot = (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies'),
    [string]$SkillDir
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$source = (Resolve-Path -LiteralPath $InputFile).Path
$config = (Resolve-Path -LiteralPath $ConfigFile).Path
if (-not $OutputFile) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $OutputFile = Join-Path $projectRoot ("outputs\{0}-图册-{1}.pptx" -f [System.IO.Path]::GetFileNameWithoutExtension($source), $stamp)
}
$output = [System.IO.Path]::GetFullPath($OutputFile)
if (-not $output.StartsWith($projectRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputFile must be inside the project directory.'
}
if (Test-Path -LiteralPath $output) { throw "Output already exists: $output" }
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
$env:PYTHONIOENCODING = 'utf-8'
$env:RUNTIME_NODE_MODULES = $modules
$env:RUNTIME_NODE = $node
$env:RUNTIME_PYTHON = $python
$env:RUNTIME_BIN_DIR = $bin
$env:PRESENTATION_SKILL_DIR = $SkillDir
& $python (Join-Path $PSScriptRoot 'extract.py') --input $source --work-dir $workDir
if ($LASTEXITCODE -ne 0) { throw 'Workbook extraction failed.' }
& $node (Join-Path $PSScriptRoot 'build.mjs') --source $source --work-dir $workDir --output $output --config $config --workspace-dir $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Presentation generation failed.' }
& $python (Join-Path $PSScriptRoot 'verify.py') --work-dir $workDir --output $output
if ($LASTEXITCODE -ne 0) { throw 'Workbook to presentation verification failed.' }
Write-Output $output

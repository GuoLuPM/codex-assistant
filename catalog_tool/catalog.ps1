# Compatibility entry; the shared launcher owns Python selection.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot '..\assistant.ps1') run catalog @args

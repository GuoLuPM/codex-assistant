"""Adapt the catalogue CLI to the existing verified PowerShell PPT pipeline."""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path


def add_parser(commands):
    parser = commands.add_parser("ppt", help="Generate one verified PPT using the Codex presentation runtime")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--ids", nargs="+")
    selection.add_argument("--input", type=Path)
    parser.add_argument("--price-fields", nargs="+")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--style", type=Path)
    parser.add_argument("--map", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--skill-dir", type=Path)


def invocation(args, catalog_script=None):
    if args.map and not args.input:
        raise ValueError("ppt --map requires --input")
    params = {"IndexDir": str(args.index_dir.resolve())}
    if catalog_script:
        params["CatalogScript"] = str(Path(catalog_script).resolve())
    for key, value in {"ProductIds": args.ids, "PriceFields": args.price_fields}.items():
        if value:
            params[key] = value
    for key, value in {"InputFile": args.input, "OutputFile": args.output, "ConfigFile": args.style,
                       "ImportMap": args.map, "CatalogConfigFile": args.config,
                       "RuntimeRoot": args.runtime_root, "SkillDir": args.skill_dir}.items():
        if value:
            params[key] = str(value.resolve())
    data = {"script": str(Path(__file__).with_name("run.ps1")), "parameters": params}
    payload = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("ascii")
    # Data travels in JSON, never interpolated as PowerShell source.
    script = """$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    $data = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('PAYLOAD')) | ConvertFrom-Json
    $parameters = @{}
    foreach ($p in $data.parameters.PSObject.Properties) { $parameters[$p.Name] = $p.Value }
    & $data.script @parameters
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
""".replace("PAYLOAD", payload)
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def run(args, catalog_script=None):
    if os.name != "nt":
        raise ValueError("PPT export currently requires Windows and the Codex presentation runtime")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise ValueError("PowerShell not found")
    return subprocess.run([shell, "-NoProfile", "-NonInteractive", "-EncodedCommand", invocation(args, catalog_script)], check=False).returncode

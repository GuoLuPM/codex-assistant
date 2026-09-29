"""Persist device-local paths; proprietary PPT components stay on their own device."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def probe_ppt(root, skill):
    """Check executable imports; a full export is a separate deployment check."""
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'RUNTIME_NODE_MODULES': str(root / 'node/node_modules')}
    node_probe = '''
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
const resolve = createRequire(path.join(process.env.RUNTIME_NODE_MODULES, '__probe__.cjs'));
const { Presentation, PresentationFile } = await import(pathToFileURL(resolve.resolve('@oai/artifact-tool')).href);
const helper = await import(pathToFileURL(process.argv[1]).href);
if (typeof PresentationFile.exportPptx !== 'function' || typeof helper.finalizePresentation !== 'function') throw Error('Unsupported PPT components');
Presentation.create({ slideSize: { width: 1280, height: 690 } }).slides.add();
console.log('ok');
'''
    commands = [
        [str(root / 'python/python.exe'), '-B', '-c', 'import openpyxl,PIL,pptx; print("ok")'],
        [str(root / 'node/bin/node.exe'), '--input-type=module', '-e', node_probe, str(skill / 'container_tools/artifact_tool_utils.mjs')],
    ]
    for command in commands:
        try:
            result = subprocess.run(command, text=True, encoding='utf-8', errors='replace', capture_output=True, check=True, env=environment, timeout=60)
        except subprocess.CalledProcessError as error:
            raise ValueError('PPT component probe failed: ' + (error.stderr or error.stdout or str(error))[-1200:]) from error
        except (OSError, subprocess.TimeoutExpired) as error:
            raise ValueError('PPT component probe failed: ' + str(error)) from error
        if result.stdout.strip() != 'ok': raise ValueError('Unexpected PPT component probe response')


def configure(project, python=None, runtime_root=None, skill_dir=None):
    project = Path(project).resolve()
    config_path = project / 'environment.local.json'
    config = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {'version': 1}
    if not isinstance(config, dict) or config.get('version') != 1:
        raise ValueError('Unsupported environment.local.json; existing configuration preserved')
    if config_path.exists() and not config.get('python'):
        raise ValueError('Existing configuration has no Python path; inspect it before retrying')
    # Preserve interpreter links: resolving a venv's python can select its base environment.
    python = Path(python or os.environ.get('ASSISTANT_PYTHON') or config.get('python') or sys.executable).absolute()
    if not (project / 'assistant.py').is_file() or not python.is_file():
        raise ValueError('Project or Python executable missing')
    probe = subprocess.run([str(python), '-B', '-c', 'import sys,sqlite3; assert sys.version_info >= (3,11); c=sqlite3.connect(":memory:"); c.execute("create virtual table t using fts5(x)"); print("ok")'],
                           text=True, capture_output=True, check=True, timeout=30)
    if probe.stdout.strip() != 'ok': raise ValueError('Python/SQLite FTS5 probe failed')
    profile = Path(os.environ.get('USERPROFILE', Path.home()))
    selected_root = runtime_root or os.environ.get('ASSISTANT_RUNTIME_ROOT') or config.get('runtime_root')
    root = Path(selected_root) if selected_root else profile / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    selected_skill = skill_dir or os.environ.get('ASSISTANT_PRESENTATIONS_SKILL') or config.get('presentations_skill')
    if not selected_skill:
        base = profile / '.codex/plugins/cache/openai-primary-runtime/presentations'
        versions = sorted((p for p in base.glob('*') if p.is_dir()), key=lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name)), reverse=True)
        if versions: selected_skill = versions[0] / 'skills/presentations'
    skill = Path(selected_skill).resolve() if selected_skill else None
    missing = [name for name in ('python/python.exe', 'node/bin/node.exe', 'node/node_modules/@oai/artifact-tool/package.json') if not (root / name).is_file()]
    if not skill or not (skill / 'container_tools/artifact_tool_utils.mjs').is_file(): missing.append('presentations skill')
    if not missing:
        try: probe_ppt(root.resolve(), skill)
        except ValueError as error: missing.append(str(error))
    if missing and (runtime_root or skill_dir or os.environ.get('ASSISTANT_RUNTIME_ROOT') or os.environ.get('ASSISTANT_PRESENTATIONS_SKILL') or config.get('runtime_root') or config.get('presentations_skill')):
        raise ValueError('Configured PPT paths unusable; existing configuration preserved: ' + ', '.join(missing))
    config.update(version=1, python=str(python))
    if not missing: config.update(runtime_root=str(root.resolve()), presentations_skill=str(skill))
    temporary = project / 'environment.local.json.tmp'
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(config_path)
    return {'project': str(project), 'python': str(python), 'base_ready': True, 'ppt_ready': not missing, 'ppt_missing': missing,
            'ppt_verified': False,
            'next': 'Run scripts/check_windows_deployment.py --ppt' if not missing else 'Use Codex load_workspace_dependencies and discover Presentations skill, then rerun configure_windows.py with their paths'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--python', type=Path, help='Explicitly replace Python; omitted preserves the configured path')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--skill-dir', type=Path)
    args = parser.parse_args()
    try: print(json.dumps(configure(args.project_dir, args.python, args.runtime_root, args.skill_dir), ensure_ascii=False))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); sys.exit(2)

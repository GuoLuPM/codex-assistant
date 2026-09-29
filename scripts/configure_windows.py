"""Persist device-local paths; proprietary PPT components stay on their own device."""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def configure(project, python, runtime_root=None, skill_dir=None):
    project, python = Path(project).resolve(), Path(python).resolve()
    if not (project / 'assistant.py').is_file() or not python.is_file():
        raise ValueError('Project or Python executable missing')
    probe = subprocess.run([str(python), '-B', '-c', 'import sys,sqlite3; assert sys.version_info >= (3,11); c=sqlite3.connect(":memory:"); c.execute("create virtual table t using fts5(x)"); print("ok")'],
                           text=True, capture_output=True, check=True)
    if probe.stdout.strip() != 'ok': raise ValueError('Python/SQLite FTS5 probe failed')
    profile = Path(os.environ.get('USERPROFILE', Path.home()))
    selected_root = runtime_root or os.environ.get('ASSISTANT_RUNTIME_ROOT')
    root = Path(selected_root) if selected_root else profile / '.cache/codex-runtimes/codex-primary-runtime/dependencies'
    selected_skill = skill_dir or os.environ.get('ASSISTANT_PRESENTATIONS_SKILL')
    if not selected_skill:
        base = profile / '.codex/plugins/cache/openai-primary-runtime/presentations'
        versions = sorted((p for p in base.glob('*') if p.is_dir()), key=lambda p: tuple(int(x) for x in re.findall(r'\d+', p.name)), reverse=True)
        if versions: selected_skill = versions[0] / 'skills/presentations'
    skill = Path(selected_skill).resolve() if selected_skill else None
    missing = [name for name in ('python/python.exe', 'node/bin/node.exe', 'node/node_modules/@oai/artifact-tool/package.json') if not (root / name).is_file()]
    if not skill or not (skill / 'container_tools/artifact_tool_utils.mjs').is_file(): missing.append('presentations skill')
    if missing and (runtime_root or skill_dir): raise ValueError('Explicit PPT paths incomplete: ' + ', '.join(missing))
    config = {'version': 1, 'python': str(python)}
    if not missing: config.update(runtime_root=str(root.resolve()), presentations_skill=str(skill))
    temporary = project / 'environment.local.json.tmp'
    temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(project / 'environment.local.json')
    return {'project': str(project), 'python': str(python), 'base_ready': True, 'ppt_ready': not missing, 'ppt_missing': missing,
            'next': 'Run scripts/check_windows_deployment.py --ppt' if not missing else 'Use Codex load_workspace_dependencies and discover Presentations skill, then rerun configure_windows.py with their paths'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-dir', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--skill-dir', type=Path)
    args = parser.parse_args()
    try: print(json.dumps(configure(args.project_dir, args.python, args.runtime_root, args.skill_dir), ensure_ascii=False))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({'error': str(error)}, ensure_ascii=False)); sys.exit(2)

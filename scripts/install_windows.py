"""Install the verified release into empty or identical directories, without Git."""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_bundle import sha, safe_path, verify_bundle
from configure_windows import configure


def destination(value):
    path = Path(value)
    if not path.is_absolute() or path == Path(path.anchor): raise ValueError('Use an absolute non-root installation directory')
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()): raise ValueError('Install destination contains a link')
    return path.resolve()


def check_destination(path, manifest, section):
    if not path.exists() or (path.is_dir() and not any(path.iterdir())): return False
    marker = path / 'deployment.local.json'
    if not marker.is_file(): raise ValueError('Existing directory has no matching installation marker: ' + str(path))
    state = json.loads(marker.read_text(encoding='utf-8'))
    expected = {name[len(section)+1:]: digest for name, digest in manifest['files'].items() if name.startswith(section + '/')}
    if state.get('commit') != manifest['commit'] or state.get('files') != expected:
        raise ValueError('Existing installation differs. Inspect it or choose an empty destination; no files overwritten')
    for name, digest in expected.items():
        file = safe_path(path, name)
        if not file.is_file() or sha(file) != digest: raise ValueError('Installed file changed; preserving local work: ' + name)
    return True


def install_tree(bundle, target, manifest, section):
    if check_destination(target, manifest, section): return 'reused'
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.assistant-install-', dir=target.parent))
    # On failure staging is preserved for inspection; never recursively delete a
    # computed user path or partially overwrite an existing installation.
    shutil.copytree(bundle / section, staging, dirs_exist_ok=True)
    state = {'version': 1, 'commit': manifest['commit'], 'tag': manifest['tag'],
             'files': {name[len(section)+1:]: digest for name, digest in manifest['files'].items() if name.startswith(section + '/')}}
    (staging / 'deployment.local.json').write_text(json.dumps(state, indent=2), encoding='utf-8')
    if target.exists(): target.rmdir()  # succeeds only if still empty
    staging.replace(target)
    return 'installed'


def install(bundle, project, runtime, proxy=None, runtime_root=None, skill_dir=None, skip_pdf=False):
    if os.name != 'nt' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('This release supports Windows x64 only')
    bundle, project, runtime = Path(bundle).resolve(), destination(project), destination(runtime)
    if project.is_relative_to(runtime) or runtime.is_relative_to(project) or project.is_relative_to(bundle) or runtime.is_relative_to(bundle):
        raise ValueError('Bundle, project and runtime must be separate directories')
    if proxy:
        address = urllib.parse.urlsplit(proxy)
        if address.scheme not in ('http', 'https') or not address.hostname or address.username or address.password:
            raise ValueError('Use an HTTP proxy URL without credentials, e.g. http://127.0.0.1:7890')
    manifest = verify_bundle(bundle)
    check_destination(project, manifest, 'application')
    check_destination(runtime, manifest, 'runtime')
    states = {'runtime': install_tree(bundle, runtime, manifest, 'runtime'), 'project': install_tree(bundle, project, manifest, 'application')}
    python = runtime / 'python/python.exe'
    environment = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1'}
    pdf_ready = False
    if not skip_pdf:
        lock = json.loads((project / 'packaging/windows-lock.json').read_text(encoding='utf-8'))['pdf']
        request = runtime / 'pdf-install.local.txt'
        request.write_text(f"{lock['url']} --hash=sha256:{lock['sha256']}\n", encoding='utf-8')
        command = [str(python), '-B', '-m', 'pip', '--isolated', 'install', '--no-deps', '--only-binary=:all:', '--require-hashes',
                   '--disable-pip-version-check', '--no-warn-script-location', '--no-compile', '--cache-dir', str(runtime / 'cache'), '-r', str(request)]
        if proxy: command.extend(['--proxy', proxy])
        try:
            subprocess.run(command, check=True, env=environment, stdout=subprocess.DEVNULL)
            pdf_ready = True
        finally: request.unlink(missing_ok=True)
    # The bundled Python is the first-install default. A retry must not replace
    # the recipient's saved interpreter or PPT paths with discovery defaults.
    result = configure(project, None if (project / 'environment.local.json').exists() else python, runtime_root, skill_dir)
    result.update(installation=states, tag=manifest['tag'], commit=manifest['commit'], pdf_ready=pdf_ready)
    result['status'] = 'configured' if result['ppt_ready'] and pdf_ready and result['workspace_installed'] else 'partial'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--project-dir', type=Path, default=Path('D:/code/assistant'))
    parser.add_argument('--runtime-dir', type=Path, default=Path('D:/tools/codex-assistant'))
    parser.add_argument('--proxy')
    parser.add_argument('--runtime-root', type=Path)
    parser.add_argument('--skill-dir', type=Path)
    parser.add_argument('--skip-pdf', action='store_true')
    args = parser.parse_args()
    try: print(json.dumps(install(args.bundle, args.project_dir, args.runtime_dir, args.proxy, args.runtime_root, args.skill_dir, args.skip_pdf), ensure_ascii=False))
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({'status': 'incomplete', 'error': str(error), 'retry': 'Existing data was preserved; resolve the reported issue and rerun the same installer'}, ensure_ascii=False)); sys.exit(2)

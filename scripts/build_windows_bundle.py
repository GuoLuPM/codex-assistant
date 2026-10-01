"""Build one Windows x64 ZIP from committed code and pinned official downloads."""
import argparse
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from windows_bundle import safe_path, sha, verify_bundle
from audit_public import audit, private_path

ROOT = Path(__file__).resolve().parents[1]


def download(record, cache, proxy=None):
    path = cache / record['filename']
    if path.exists():
        if sha(path) != record['sha256']: raise ValueError('Cached download hash mismatch: ' + path.name)
        return path
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy, 'http': proxy}) if proxy else urllib.request.ProxyHandler())
    partial = path.with_suffix(path.suffix + '.partial')
    with opener.open(record['url'], timeout=90) as response, partial.open('wb') as target:
        shutil.copyfileobj(response, target)
    if sha(partial) != record['sha256']: raise ValueError('Downloaded hash mismatch: ' + path.name)
    partial.replace(path)
    return path


def extract(archive, root):
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            if member.is_dir(): continue
            target = safe_path(root, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(member))


def build_frontend(application, node, pnpm_js, proxy=None):
    if not node or not pnpm_js or not Path(node).is_file() or not Path(pnpm_js).is_file():
        raise ValueError('Building the workspace requires --node and --pnpm-js from the build machine')
    web = application / 'workspace_tool/web'
    command = [str(node), str(pnpm_js)]
    install = command + ['install', '--frozen-lockfile', '--ignore-scripts']
    if proxy: install += ['--proxy', proxy, '--https-proxy', proxy]
    subprocess.run(install, cwd=web, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(command + ['run', 'build'], cwd=web, check=True, stdout=subprocess.DEVNULL)
    # Include licenses for code shipped in the production browser bundle.
    licenses = []
    for name in ('react', 'react-dom', 'scheduler', 'vite'):
        candidates = list((web / 'node_modules/.pnpm').glob(name + '@*/node_modules/' + name + '/LICENSE*'))
        if not candidates: raise ValueError('Missing frontend license: ' + name)
        licenses.append(name + '\n' + candidates[0].read_text(encoding='utf-8'))
    (web / 'dist/THIRD-PARTY-LICENSES.txt').write_text('\n\n'.join(licenses), encoding='utf-8')
    # Only the built static page is redistributed; package installation stays on the builder.
    dependencies = (web / 'node_modules').resolve()
    if not dependencies.is_relative_to(application.resolve()): raise ValueError('Unsafe build dependency path')
    shutil.rmtree(dependencies)


def build(tag, output, cache, proxy=None, node=None, pnpm_js=None):
    if not tag or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-' for c in tag):
        raise ValueError('Invalid release tag')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=all'], cwd=ROOT).strip():
        raise ValueError('Commit public source before building a release')
    report = audit()
    if not report['ok']: raise ValueError('Public audit failed')
    lock = json.loads((ROOT / 'packaging/windows-lock.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    destination = output / ('codex-assistant-' + tag + '-windows-x64.zip')
    if destination.exists(): raise ValueError('Release asset already exists; choose a new output directory or tag')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    # Temporary build state is below the explicitly selected output directory.
    with tempfile.TemporaryDirectory(prefix='bundle-', dir=output) as temporary:
        root = Path(temporary) / 'codex-assistant'
        application = root / 'application'
        archive = subprocess.check_output(['git', 'archive', '--format=zip', 'HEAD'], cwd=ROOT)
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            for entry in source.infolist():
                if entry.is_dir(): continue
                if private_path(entry.filename): raise ValueError('Private source in archive: ' + entry.filename)
                target = safe_path(application, entry.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(entry))
        build_frontend(application, node, pnpm_js, proxy)
        python_root = root / 'runtime/python'
        extract(download(lock['python'], cache, proxy), python_root)
        share_lock = json.loads((ROOT / 'packaging/share-lock.json').read_text(encoding='utf-8'))
        share_root = root / 'runtime/share'
        share_root.mkdir(parents=True)
        for key, filename in (('binary', 'cloudflared.exe'), ('license', 'LICENSE')):
            shutil.copyfile(download(share_lock[key], cache, proxy), share_root / filename)
        packages = python_root / 'Lib/site-packages'
        packages.mkdir(parents=True)
        wheels = [download(record, cache, proxy) for record in lock['core'] + lock.get('workspace', [])]
        pip_wheel = next(p for p in wheels if p.name.startswith('pip-'))
        extract(pip_wheel, packages)
        (python_root / 'python313._pth').write_text('python313.zip\n.\nLib\nLib/site-packages\nimport site\n', encoding='utf-8')
        (packages / 'sitecustomize.py').write_text(
            'import os, sys\nscript = sys.argv[0] if sys.argv else ""\n'
            'if script and not script.startswith("-") and os.path.isfile(script):\n'
            '    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))\n', encoding='utf-8')
        subprocess.run([str(python_root / 'python.exe'), '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile', '--disable-pip-version-check',
                        *[str(p) for p in wheels if p != pip_wheel]], check=True, stdout=subprocess.DEVNULL)
        # This app invokes modules through Python, not auxiliary wheel scripts.
        # pip gives those scripts absolute build-machine interpreter paths.
        scripts = python_root / 'Scripts'
        if scripts.exists():
            for path in scripts.iterdir():
                if not path.is_file() or path.is_symlink(): raise ValueError('Unexpected wheel script entry')
                path.unlink()
            scripts.rmdir()
        for info in packages.glob('*.dist-info'):
            # pip records build-machine paths for direct wheel inputs. They are
            # not runtime requirements; retain upstream metadata and licenses.
            for name in ('direct_url.json', 'REQUESTED'):
                (info / name).unlink(missing_ok=True)
            record = info / 'RECORD'
            if record.exists():
                rows = list(csv.reader(io.StringIO(record.read_text(encoding='utf-8'))))
                with record.open('w', encoding='utf-8', newline='') as stream:
                    csv.writer(stream, lineterminator='\n').writerows(row for row in rows if (packages / row[0]).is_file())
        shutil.copyfile(application / 'packaging/Setup.ps1', root / 'Setup.ps1')
        shutil.copyfile(application / 'docs/WINDOWS_RELEASE.md', root / 'START-HERE.md')
        shutil.copyfile(application / 'docs/USER_GUIDE.html', root / '使用手册.html')
        manifest = {'version': 1, 'platform': 'windows-x64', 'tag': tag, 'commit': commit,
                    'python_version': lock['python']['version'], 'files': {}}
        for path in sorted(root.rglob('*')):
            if path.is_file(): manifest['files'][path.relative_to(root).as_posix()] = sha(path)
        (root / 'bundle.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
        verify_bundle(root)
        with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    entry = zipfile.ZipInfo('codex-assistant/' + path.relative_to(root).as_posix(), (2026, 1, 1, 0, 0, 0))
                    entry.compress_type = zipfile.ZIP_DEFLATED
                    target.writestr(entry, path.read_bytes())
    return {'asset': str(destination), 'sha256': sha(destination), 'bytes': destination.stat().st_size, 'commit': commit, 'tag': tag}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--proxy')
    parser.add_argument('--node', type=Path)
    parser.add_argument('--pnpm-js', type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.tag, args.output.resolve(), args.cache.resolve(), args.proxy, args.node, args.pnpm_js), ensure_ascii=False))

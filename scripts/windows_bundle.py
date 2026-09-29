"""Shared, standard-library-only checks for public Windows release payloads."""
import hashlib
import json
from pathlib import Path, PurePosixPath


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_path(root, relative):
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise ValueError('Unsafe payload path')
    part = PurePosixPath(relative)
    if part.is_absolute() or not part.parts or any(p in ('.', '..') for p in part.parts):
        raise ValueError('Unsafe payload path')
    root = Path(root).absolute()
    path = root.joinpath(*part.parts)
    for entry in (root, *path.relative_to(root).parents):
        candidate = entry if entry.is_absolute() else root / entry
        if candidate.is_symlink() or (hasattr(candidate, 'is_junction') and candidate.is_junction()):
            raise ValueError('Payload cannot contain links')
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Payload escapes its directory')
    return path


def verify_bundle(root):
    root = Path(root)
    manifest = json.loads((root / 'bundle.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or manifest.get('platform') != 'windows-x64' or not isinstance(manifest.get('files'), dict) or not manifest['files']:
        raise ValueError('Unsupported bundle manifest')
    for name, digest in manifest['files'].items():
        path = safe_path(root, name)
        if not path.is_file() or sha(path) != digest:
            raise ValueError('Payload missing or changed: ' + name)
    actual = {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} - {'bundle.json'}
    if actual != set(manifest['files']):
        raise ValueError('Bundle contains undeclared payloads')
    for required in ('runtime/python/python.exe', 'application/assistant.py', 'Setup.ps1'):
        if required not in manifest['files']: raise ValueError('Incomplete Windows bundle')
    return manifest

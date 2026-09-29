import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from windows_bundle import safe_path, verify_bundle
from install_windows import check_destination, install_tree


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bundle = self.root / 'bundle'
        files = {'application/assistant.py': b'public code', 'runtime/python/python.exe': b'fake fixture', 'Setup.ps1': b'bootstrap'}
        manifest = {'version': 1, 'platform': 'windows-x64', 'tag': 'test', 'commit': 'abc', 'files': {}}
        for name, data in files.items():
            target = self.bundle / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            manifest['files'][name] = hashlib.sha256(data).hexdigest()
        self.manifest = manifest
        (self.bundle / 'bundle.json').write_text(json.dumps(manifest), encoding='utf-8')

    def tearDown(self): self.tmp.cleanup()

    def test_payload_tamper_extra_file_and_traversal_are_rejected(self):
        self.assertEqual(verify_bundle(self.bundle)['tag'], 'test')
        for name in ('../outside', 'C:/outside', '/absolute', 'runtime\\escape'):
            with self.assertRaises(ValueError): safe_path(self.bundle, name)
        (self.bundle / 'extra.txt').write_text('unlisted', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'undeclared'): verify_bundle(self.bundle)
        (self.bundle / 'extra.txt').unlink()
        (self.bundle / 'application/assistant.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'changed'): verify_bundle(self.bundle)

    def test_install_resumes_identical_payload_and_preserves_private_data(self):
        target = self.root / 'code space'
        self.assertEqual(install_tree(self.bundle, target, self.manifest, 'application'), 'installed')
        private = target / 'data/keep.txt'
        private.parent.mkdir(); private.write_text('keep', encoding='utf-8')
        self.assertEqual(install_tree(self.bundle, target, self.manifest, 'application'), 'reused')
        self.assertEqual(private.read_text(), 'keep')
        (target / 'assistant.py').write_text('local edit', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'preserving local work'): check_destination(target, self.manifest, 'application')
        other = self.root / 'other'; other.mkdir(); (other / 'user.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError, 'marker'): install_tree(self.bundle, other, self.manifest, 'application')
        self.assertEqual((other / 'user.txt').read_text(), 'keep')

    @unittest.skipUnless(os.name == 'nt', 'PowerShell launcher integration')
    def test_launcher_uses_local_config_from_another_working_directory(self):
        project = self.root / 'project space'
        (project / 'scripts').mkdir(parents=True)
        for name in ('assistant.ps1', 'assistant.py', 'tools.json'):
            shutil.copyfile(ROOT / name, project / name)
        for tool in json.loads((project / 'tools.json').read_text(encoding='utf-8'))['tools']:
            for key in ('entrypoint', 'guide'):
                path = project / tool[key]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('fixture', encoding='utf-8')
        shutil.copyfile(ROOT / 'scripts/environment.ps1', project / 'scripts/environment.ps1')
        (project / 'environment.local.json').write_text(json.dumps({'version': 1, 'python': sys.executable}), encoding='utf-8')
        environment = {k: v for k, v in os.environ.items() if not k.startswith('ASSISTANT_')}
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(project / 'assistant.ps1'), 'doctor'],
                                cwd=self.root, env=environment, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(project).replace('\\', '\\\\').encode(), result.stdout)
        environment['ASSISTANT_PYTHON'] = str(project / 'missing.exe')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(project / 'assistant.ps1'), 'doctor'],
                                cwd=self.root, env=environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from windows_bundle import safe_path, verify_bundle
from install_windows import check_destination, install, install_tree
from configure_windows import configure


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

    @unittest.skipUnless(os.name == 'nt', 'Windows installer')
    def test_default_runtime_is_inside_project_and_retries_preserve_private_data(self):
        project = self.root / 'project space'
        runtime = project / 'data/runtime'
        with patch('install_windows.configure', return_value={'ppt_ready': False, 'workspace_installed': False}) as probe:
            result = install(self.bundle, project, skip_pdf=True)
            self.assertEqual(result['installation'], {'project': 'installed', 'runtime': 'installed'})
            self.assertEqual(probe.call_args.args[1], runtime / 'python/python.exe')
            self.assertEqual((runtime / 'python/python.exe').read_bytes(), b'fake fixture')
            private = project / 'data/keep.txt'
            private.write_text('keep', encoding='utf-8')
            result = install(self.bundle, project, skip_pdf=True)
            self.assertEqual(result['installation'], {'project': 'reused', 'runtime': 'reused'})
            self.assertEqual(private.read_text(), 'keep')

    @unittest.skipUnless(os.name == 'nt', 'Windows installer')
    def test_explicit_external_runtime_remains_supported(self):
        project, runtime = self.root / 'project', self.root / 'custom runtime'
        with patch('install_windows.configure', return_value={'ppt_ready': False, 'workspace_installed': False}):
            result = install(self.bundle, project, runtime, skip_pdf=True)
        self.assertEqual(result['installation'], {'project': 'installed', 'runtime': 'installed'})
        self.assertTrue((runtime / 'python/python.exe').is_file())
        self.assertFalse((project / 'data/runtime').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows installer')
    def test_unsafe_runtime_or_existing_user_directory_is_rejected_before_writes(self):
        project = self.root / 'project'
        for runtime in (project, project / 'scripts', project / 'data', self.bundle / 'runtime', self.root):
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                install(self.bundle, project, runtime, skip_pdf=True)
            self.assertFalse(project.exists())
        project.mkdir()
        (project / 'user.txt').write_text('keep', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'marker'):
            install(self.bundle, project, skip_pdf=True)
        self.assertEqual([p.name for p in project.iterdir()], ['user.txt'])
        self.assertEqual((project / 'user.txt').read_text(), 'keep')

    def test_configuration_preserves_saved_paths_and_rejects_broken_components(self):
        project = self.bundle / 'application'
        runtime, skill = self.root / 'custom runtime', self.root / 'custom skill'
        for target in (runtime / 'python/python.exe', runtime / 'node/bin/node.exe',
                       runtime / 'node/node_modules/@oai/artifact-tool/package.json', skill / 'container_tools/artifact_tool_utils.mjs'):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b'not an executable')
        config = {'version': 1, 'python': sys.executable, 'runtime_root': str(runtime), 'presentations_skill': str(skill), 'user_setting': 'keep'}
        path = project / 'environment.local.json'
        path.write_text(json.dumps(config), encoding='utf-8')
        environment = {key: value for key, value in os.environ.items() if not key.startswith('ASSISTANT_')}
        with patch.dict(os.environ, environment, clear=True):
            with patch('configure_windows.probe_ppt') as probe:
                result = configure(project)
                self.assertTrue(result['ppt_ready'])
                self.assertFalse(result['ppt_verified'])
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')), config)
                probe.assert_called_once_with(runtime.resolve(), skill.resolve())
            previous = path.read_bytes()
            # File names alone cannot pass readiness: these are real invalid
            # executable fixtures, not a mocked successful component probe.
            with self.assertRaisesRegex(ValueError, 'component probe failed'):
                configure(project)
            self.assertEqual(path.read_bytes(), previous)
            with self.assertRaisesRegex(ValueError, 'unusable'):
                configure(project, runtime_root=self.root / 'missing')
            self.assertEqual(path.read_bytes(), previous)

    def test_absent_codex_components_leave_an_explicit_partial_configuration(self):
        project = self.bundle / 'application'
        environment = {key: value for key, value in os.environ.items() if not key.startswith('ASSISTANT_')}
        environment['USERPROFILE'] = str(self.root / 'new user')
        with patch.dict(os.environ, environment, clear=True):
            result = configure(project, sys.executable)
        self.assertTrue(result['base_ready'])
        self.assertFalse(result['ppt_ready'])
        self.assertTrue(result['ppt_missing'])
        self.assertEqual(json.loads((project / 'environment.local.json').read_text(encoding='utf-8')), {'version': 1, 'python': str(Path(sys.executable).absolute())})

    @unittest.skipIf(os.name == 'nt', 'POSIX interpreter links')
    def test_configured_python_link_is_not_replaced_by_its_base_interpreter(self):
        project = self.bundle / 'application'
        interpreter = self.root / 'python-link'
        interpreter.symlink_to(sys.executable)
        environment = {key: value for key, value in os.environ.items() if not key.startswith('ASSISTANT_')}
        environment['USERPROFILE'] = str(self.root / 'new user')
        with patch.dict(os.environ, environment, clear=True):
            result = configure(project, interpreter)
        self.assertEqual(result['python'], str(interpreter))
        self.assertEqual(json.loads((project / 'environment.local.json').read_text(encoding='utf-8'))['python'], str(interpreter))

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
        self.assertEqual(Path(json.loads(result.stdout)['project']).resolve(), project.resolve())
        environment['ASSISTANT_PYTHON'] = str(project / 'missing.exe')
        result = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(project / 'assistant.ps1'), 'doctor'],
                                cwd=self.root, env=environment, capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__': unittest.main()

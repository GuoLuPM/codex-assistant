import os
import subprocess
import sys
import time
import unittest
from workspace_tool.processes import OwnedProcessGroup
from workspace_tool.cli import process_alive


@unittest.skipUnless(os.name == 'nt', 'Windows owned-process lifecycle')
class ProcessTests(unittest.TestCase):
    def test_close_cleans_only_owned_tree(self):
        sibling = subprocess.Popen([sys._base_executable, '-c', 'import time;time.sleep(15)'])
        root = subprocess.Popen([sys._base_executable, '-u', '-c',
            'import subprocess,sys,time;input();p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(15)"]);print(p.pid,flush=True);time.sleep(15)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        group = None
        try:
            group = OwnedProcessGroup(root.pid)
            root.stdin.write('\n'); root.stdin.flush()
            child = int(root.stdout.readline())
            self.assertTrue(process_alive(child))
            group.close(); root.wait(timeout=5)
            for _ in range(50):
                if not process_alive(child): break
                time.sleep(.05)
            self.assertFalse(process_alive(child))
            self.assertIsNone(sibling.poll())
        finally:
            if group: group.close()
            for process in (root, sibling):
                if process.poll() is None: process.terminate()
                process.wait(timeout=5)
            root.stdin.close(); root.stdout.close()

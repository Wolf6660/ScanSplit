import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[1] / 'entrypoint.sh'


class BootstrapTests(unittest.TestCase):
    def test_updates_and_falls_back_to_last_working_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            def git(*args):
                return subprocess.check_output(['git','-C',str(source),*args],stderr=subprocess.DEVNULL,text=True).strip()
            git('init','--initial-branch=main'); git('config','user.name','ScanSplit Test'); git('config','user.email','test@example.invalid')
            (source/'scansplit').mkdir(); (source/'requirements.txt').write_text('')
            (source/'scansplit/__init__.py').write_text(''); (source/'scansplit/server.py').write_text('# fixture')
            main = source/'scansplit/__main__.py'
            def commit(code):
                main.write_text(code); git('add','.'); git('commit','-m','Test release'); return git('rev-parse','HEAD')
            first = commit('print("release-one")')
            env = {**os.environ,'SOURCE_REPO':str(source),'SOURCE_REF':'main','SCANSPLIT_RUNTIME_DIR':str(root/'runtime'),
                   'SCANSPLIT_BOOTSTRAP_PYTHON':sys.executable,'PIP_NO_INDEX':'1'}
            def run(extra=None):
                return subprocess.run(['sh',str(ENTRYPOINT),'--check'],env={**env,**(extra or {})},capture_output=True,text=True,timeout=90)
            result = run(); self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('release-one',result.stdout)
            self.assertEqual((root/'runtime/current').resolve().name,first)
            second = commit('print("release-two")')
            result = run(); self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('release-two',result.stdout); self.assertEqual((root/'runtime/current').resolve().name,second)
            commit('raise RuntimeError("Broken release")')
            result = run(); self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('release-two',result.stdout); self.assertIn('Cache',result.stderr)
            self.assertEqual((root/'runtime/current').resolve().name,second)
            result = run({'SOURCE_REPO':str(root/'unreachable')})
            self.assertEqual(result.returncode,0,result.stderr); self.assertIn('release-two',result.stdout)
            result = run({'SCANSPLIT_RUNTIME_DIR':str(root/'empty-runtime'),'SOURCE_REPO':str(root/'unreachable')})
            self.assertNotEqual(result.returncode,0)

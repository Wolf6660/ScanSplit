import os
import shutil
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
            (source/'scansplit').mkdir()
            # Real dependency, fresh venv, package indexes unavailable: this is
            # the first-start scenario that previously failed on the NAS.
            project = ENTRYPOINT.parent
            shutil.copytree(project/'vendor',source/'vendor')
            shutil.copyfile(project/'requirements.txt',source/'requirements.txt')
            (source/'scansplit/__init__.py').write_text(''); (source/'scansplit/server.py').write_text('# fixture')
            main = source/'scansplit/__main__.py'
            def commit(code):
                main.write_text(code); git('add','.'); git('commit','-m','Test release'); return git('rev-parse','HEAD')
            prelude = 'import pypdf\nassert pypdf.__version__ == "6.10.0"\n'
            first = commit(prelude+'print("release-one")')
            env = {**os.environ,'SOURCE_REPO':str(source),'SOURCE_REF':'main','SCANSPLIT_RUNTIME_DIR':str(root/'runtime'),
                   'SCANSPLIT_BOOTSTRAP_PYTHON':sys.executable,'PIP_NO_INDEX':'1'}
            def run(extra=None):
                return subprocess.run(['sh',str(ENTRYPOINT),'--check'],env={**env,**(extra or {})},capture_output=True,text=True,timeout=90)
            result = run(); self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('release-one',result.stdout)
            self.assertEqual((root/'runtime/current').resolve().name,first)
            second = commit(prelude+'print("release-two")')
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

    def test_offline_install_rejects_tampered_wheel(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); vendor = root/'vendor'; vendor.mkdir()
            project = ENTRYPOINT.parent
            shutil.copyfile(project/'requirements.txt',root/'requirements.txt')
            wheel = next((project/'vendor').glob('*.whl'))
            (vendor/wheel.name).write_bytes(wheel.read_bytes()+b'tampered')
            subprocess.run([sys.executable,'-m','venv',str(root/'venv')],check=True,capture_output=True)
            result = subprocess.run([str(root/'venv/bin/python'),'-m','pip','install','--disable-pip-version-check',
                '--no-index','--find-links',str(vendor),'--require-hashes','-r',str(root/'requirements.txt')],
                env={**os.environ,'PIP_NO_INDEX':'1'},capture_output=True,text=True,timeout=60)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('HASHES',result.stderr.upper())

    def test_original_image_bootstrap_loads_new_release_without_pypi(self):
        """Run the actual script shipped in the first image, not an approximation."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root/'source'; source.mkdir()
            project = ENTRYPOINT.parent
            shutil.copytree(project/'vendor',source/'vendor')
            shutil.copyfile(project/'requirements.txt',source/'requirements.txt')
            (source/'scansplit').mkdir()
            (source/'scansplit/__init__.py').write_text('')
            (source/'scansplit/server.py').write_text('# fixture')
            (source/'scansplit/__main__.py').write_text('import pypdf\nassert pypdf.__version__ == "6.10.0"\nprint("legacy-bootstrap-upgrade-ok")\n')
            def git(*args):
                subprocess.run(['git','-C',str(source),*args],check=True,capture_output=True)
            git('init','--initial-branch=main'); git('config','user.name','ScanSplit Test')
            git('config','user.email','test@example.invalid'); git('add','.'); git('commit','-m','Offline compatible release')
            env = {**os.environ,'SOURCE_REPO':str(source),'SOURCE_REF':'main',
                   'SCANSPLIT_RUNTIME_DIR':str(root/'runtime'),'SCANSPLIT_BOOTSTRAP_PYTHON':sys.executable,
                   'PIP_INDEX_URL':'http://127.0.0.1:9/simple','PIP_CONFIG_FILE':os.devnull,'PIP_DEFAULT_TIMEOUT':'1'}
            env.pop('PIP_NO_INDEX',None)
            result = subprocess.run(['sh',str(project/'tests/fixtures/entrypoint-v1.sh'),'--check'],
                                    cwd=root,env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn('legacy-bootstrap-upgrade-ok',result.stdout)
            self.assertNotIn('Retrying',result.stderr)
            self.assertNotIn('Looking in indexes',result.stdout)

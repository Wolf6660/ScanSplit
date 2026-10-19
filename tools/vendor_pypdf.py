"""Repackage the unchanged installed pure-Python pypdf distribution for offline use.

Uses upstream metadata/license, excludes installation-local files, and creates a
deterministic wheel with a freshly generated RECORD. Does not fetch from a network.
"""
import base64
import csv
import hashlib
import io
from importlib.metadata import distribution
from pathlib import Path
import zipfile

VERSION = "6.10.0"
root = Path(__file__).resolve().parents[1]
dist = distribution("pypdf")
if dist.version != VERSION:
    raise SystemExit(f"Install pypdf {VERSION} before rebuilding its offline wheel")
info = f"pypdf-{VERSION}.dist-info"
files = {}
for entry in dist.files:
    name = entry.as_posix()
    if entry.parts[0] not in ("pypdf", info) or "__pycache__" in entry.parts or name.endswith(".pyc"):
        continue
    if name in {f"{info}/{n}" for n in ("RECORD", "INSTALLER", "REQUESTED", "direct_url.json")}:
        continue
    files[name] = dist.locate_file(entry).read_bytes()
assert f"{info}/licenses/LICENSE" in files and "pypdf/__init__.py" in files
record = io.StringIO(newline="")
writer = csv.writer(record, lineterminator="\n")
for name, content in sorted(files.items()):
    digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
    writer.writerow([name,"sha256="+digest,str(len(content))])
writer.writerow([f"{info}/RECORD","",""])
files[f"{info}/RECORD"] = record.getvalue().encode()
vendor = root / "vendor"
vendor.mkdir(exist_ok=True)
path = vendor / f"pypdf-{VERSION}-py3-none-any.whl"
with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as wheel:
    for name, content in sorted(files.items()):
        entry = zipfile.ZipInfo(name,date_time=(2026,4,10,0,0,0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = 0o644 << 16
        wheel.writestr(entry,content)
digest = hashlib.sha256(path.read_bytes()).hexdigest()
(root/"requirements.txt").write_text(f"--no-index\n--find-links vendor\n--require-hashes\npypdf=={VERSION} --hash=sha256:{digest}\n")
(vendor/"SHA256SUMS").write_text(f"{digest}  {path.name}\n")
(vendor/"pypdf-LICENSE.txt").write_bytes(files[f"{info}/licenses/LICENSE"])
print(f"Created {path.name}, SHA256 {digest}")

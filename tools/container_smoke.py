"""Linux-container end-to-end test using only a synthetic document."""
import io
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from helpers import fixture_pdf
from pypdf import PdfReader

base = sys.argv[1] if len(sys.argv) > 1 else 'http://127.0.0.1:18769'


def request(path, data=None, headers=None):
    if isinstance(data,dict):
        data = json.dumps(data).encode(); headers = {'Content-Type':'application/json'}
    req = urllib.request.Request(base+path,data=data,headers=headers or {})
    with urllib.request.urlopen(req,timeout=30) as response:
        body = response.read()
        return json.loads(body) if response.headers['Content-Type'].startswith('application/json') else body


for attempt in range(90):
    try:
        health = request('/api/health'); break
    except OSError:
        time.sleep(2)
else:
    raise SystemExit('Container did not become ready')
assert health['ocr_available'],health
assert health['renderer_available'],health
doc = request('/api/documents',fixture_pdf(),{'Content-Type':'application/pdf','X-File-Name':'Synthetic.pdf'})
choices = [{'mode':'whole','cut':.5,'rotation':0},{'mode':'skip','cut':.5,'rotation':0}]
for ocr in (True,False):
    payload = {'choices':choices}
    if not ocr: payload['ocr'] = False  # Missing key must default to True.
    job = request(f'/api/documents/{doc["id"]}/jobs',payload)
    for _ in range(120):
        job = request(f'/api/documents/{doc["id"]}/jobs/{job["id"]}')
        if job['state'] not in ('running','queued'): break
        time.sleep(1)
    assert job['state'] == 'completed',job
    assert job['ocr'] is ocr,job
    pdf = request(f'/api/documents/{doc["id"]}/jobs/{job["id"]}/result.pdf')
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    assert 'ScanSplit' in reader.pages[0].extract_text()
    print(f'Container upload -> export -> download passed (OCR={ocr})')

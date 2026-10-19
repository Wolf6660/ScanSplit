import io
import json
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from pypdf import PdfReader
from scansplit.server import Handler, State
from helpers import fixture_pdf


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.state = State(cls.temp.name)
        handler = type('TestHandler',(Handler,),{'state':cls.state})
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True); cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.thread.join(); cls.state.close(); cls.server.server_close(); cls.temp.cleanup()

    def request(self,path,method='GET',data=None,headers=None):
        if isinstance(data,dict):
            data = json.dumps(data).encode(); headers = {**(headers or {}),'Content-Type':'application/json'}
        req = urllib.request.Request(self.base+path,data=data,method=method,headers=headers or {})
        try:
            with urllib.request.urlopen(req,timeout=30) as response:
                body = response.read()
                return response.status,body,response.headers
        except urllib.error.HTTPError as response:
            return response.code,response.read(),response.headers

    def upload(self):
        status,body,_ = self.request('/api/documents','POST',fixture_pdf(),{'Content-Type':'application/pdf','X-File-Name':'Testscan.pdf'})
        self.assertEqual(status,201,body)
        return json.loads(body)

    def test_health_frontend_and_red_default_ocr(self):
        status,body,_ = self.request('/api/health'); self.assertEqual(status,200)
        self.assertIn('ocr_available',json.loads(body))
        status,body,headers = self.request('/')
        self.assertEqual(status,200); self.assertIn(b'id="ocr-toggle" type="checkbox" role="switch" checked',body)
        self.assertIn(b'class="ocr-card active"',body); self.assertIn('Content-Security-Policy',headers)

    def test_real_upload_preview_export_download_delete(self):
        doc = self.upload(); ident = doc['id']
        status,png,_ = self.request(f'/api/documents/{ident}/preview/0?rotation=90')
        self.assertEqual(status,200,png[:100]); self.assertTrue(png.startswith(b'\x89PNG'))
        width,height = struct.unpack('>II',png[16:24]); self.assertGreater(width,height)
        status,body,_ = self.request(f'/api/documents/{ident}/jobs','POST',{'choices':doc['pages'],'ocr':False})
        self.assertEqual(status,202,body); job = json.loads(body)
        for _ in range(100):
            status,body,_ = self.request(f'/api/documents/{ident}/jobs/{job["id"]}')
            job = json.loads(body)
            if job['state'] not in ('queued','running'): break
            time.sleep(.05)
        self.assertEqual(job['state'],'completed',job)
        status,pdf,headers = self.request(f'/api/documents/{ident}/jobs/{job["id"]}/result.pdf')
        self.assertEqual(status,200); self.assertEqual(len(PdfReader(io.BytesIO(pdf)).pages),3)
        self.assertIn('attachment',headers['Content-Disposition'])
        status,_,_ = self.request(f'/api/documents/{ident}','DELETE'); self.assertEqual(status,200)
        status,_,_ = self.request(f'/api/documents/{ident}'); self.assertEqual(status,404)

    def test_missing_ocr_is_not_silently_disabled(self):
        if self.state.ocr_available: self.skipTest('Real OCR is available; tested by engine integration test')
        doc = self.upload()
        status,body,_ = self.request(f'/api/documents/{doc["id"]}/jobs','POST',{'choices':doc['pages']})
        self.assertEqual(status,422); self.assertIn('error',json.loads(body))

    def test_cross_origin_and_path_traversal_rejected(self):
        status,_,_ = self.request('/api/documents','POST',fixture_pdf(),{'Content-Type':'application/pdf','Origin':'https://foreign.invalid'})
        self.assertEqual(status,403)
        for path in ('/api/documents/../etc/passwd','/../requirements.txt','/.git/config'):
            status,_,_ = self.request(path); self.assertEqual(status,404)

    def test_invalid_upload_and_invalid_choices(self):
        status,_,_ = self.request('/api/documents','POST',b'not a pdf',{'Content-Type':'application/pdf'})
        self.assertEqual(status,400)
        doc = self.upload()
        status,_,_ = self.request(f'/api/documents/{doc["id"]}/jobs','POST',{'ocr':False,'choices':[]})
        self.assertEqual(status,400)

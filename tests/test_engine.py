import hashlib
import io
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from pypdf import PdfReader
from scansplit.engine import A4, Cancelled, Control, export_pdf, inspect_pdf, output_count, render_preview, run_tool, validate_choices
from helpers import fixture_pdf


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source.pdf'
        self.target = Path(self.temp.name) / 'target.pdf'
        self.source.write_bytes(fixture_pdf())
        self.choices = inspect_pdf(self.source)

    def test_mixed_rotations_a4_and_unchanged_source(self):
        before = hashlib.sha256(self.source.read_bytes()).digest()
        self.assertEqual([c['mode'] for c in self.choices],['whole','split'])
        export_pdf(self.source,self.target,self.choices,ocr=False)
        pages = PdfReader(self.target).pages
        self.assertEqual(len(pages),3)
        for page in pages:
            self.assertAlmostEqual(float(page.mediabox.width),A4[0],places=3)
            self.assertAlmostEqual(float(page.mediabox.height),A4[1],places=3)
            self.assertEqual(page.rotation,0)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).digest(),before)

    def test_half_modes_exclusion_and_rotation(self):
        for mode in ('left','right','whole','split'):
            choices = [{'mode':mode,'cut':.53,'rotation':90},{'mode':'skip','cut':.5,'rotation':0}]
            export_pdf(self.source,self.target,choices,ocr=False)
            self.assertEqual(len(PdfReader(self.target).pages),2 if mode == 'split' else 1)

    def test_invalid_selections_and_original_overwrite(self):
        for choices in ([],[{'mode':'skip'}]*2,[{'mode':'right','cut':0}]*2,
                        [{'mode':'whole','rotation':45}]*2,[{'mode':'whole','cut':True}]*2):
            with self.assertRaises(ValueError):
                validate_choices(choices,2)
        with self.assertRaises(ValueError):
            export_pdf(self.source,self.source,self.choices,ocr=False)

    def test_cancel_keeps_existing_file(self):
        self.target.write_bytes(b'existing')
        control = Control(); control.event.set()
        with self.assertRaises(Cancelled):
            export_pdf(self.source,self.target,self.choices,ocr=False,control=control)
        self.assertEqual(self.target.read_bytes(),b'existing')

    def test_external_process_cancelled_promptly(self):
        control = Control(); timer = threading.Timer(.2,control.event.set); timer.start()
        start = time.monotonic()
        try:
            with self.assertRaises(Cancelled):
                run_tool([sys.executable,'-c','import time; time.sleep(20)'],control)
        finally:
            timer.cancel()
        self.assertLess(time.monotonic()-start,5)

    @unittest.skipUnless(shutil.which('pdftoppm'),'Poppler is not installed')
    def test_preview_rotation(self):
        import struct
        for rotation in (0,90):
            png = Path(self.temp.name) / f'preview-{rotation}.png'
            render_preview(self.source,0,rotation,500,png)
            width,height = struct.unpack('>II',png.read_bytes()[16:24])
            self.assertEqual(width > height,rotation == 90)

    @unittest.skipUnless(shutil.which('tesseract') and shutil.which('pdftoppm'),'Tesseract/Poppler not installed')
    def test_real_german_ocr(self):
        choices = [{'mode':'whole','cut':.5,'rotation':0},{'mode':'skip','cut':.5,'rotation':0}]
        export_pdf(self.source,self.target,choices,ocr=True)
        text = PdfReader(self.target).pages[0].extract_text()
        self.assertIn('ScanSplit',text)
        self.assertIn('12345',text)

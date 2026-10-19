"""Local PDF splitting and German Tesseract OCR. No web framework required."""
import copy
import os
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from pypdf import PageObject, PdfReader, PdfWriter, Transformation
from pypdf.generic import RectangleObject

A4 = (595.2756, 841.8898)
MODES = {"whole", "split", "left", "right", "skip"}


class Cancelled(Exception):
    pass


class Control:
    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            raise Cancelled("Export abgebrochen.")


def run_tool(args, control, *, timeout=300, cwd=None):
    """Bound external processes; stop their process group on cancellation."""
    control.check()
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(args, cwd=cwd, stdout=subprocess.DEVNULL, stderr=log,
                                   start_new_session=True)
        start = time.monotonic()
        try:
            while process.poll() is None:
                control.check()
                if time.monotonic() - start > timeout:
                    raise RuntimeError("Zeitlimit bei der Seitenverarbeitung überschritten.")
                control.event.wait(0.1)
            if process.returncode:
                log.seek(0, 2)
                log.seek(max(0, log.tell() - 1800))
                detail = log.read().decode("utf-8", "replace").strip()
                raise RuntimeError("PDF-/OCR-Verarbeitung fehlgeschlagen: " + detail)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                    process.wait(timeout=3)
                except (ProcessLookupError, subprocess.TimeoutExpired):
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
            process.wait()
    control.check()


def inspect_pdf(path, max_pages=400):
    with open(path, "rb") as stream:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError("Bitte eine unverschlüsselte PDF hochladen.")
        if not 1 <= len(reader.pages) <= max_pages:
            raise ValueError(f"Die PDF muss zwischen 1 und {max_pages} Seiten enthalten.")
        pages = []
        for page in reader.pages:
            width, height = float(page.cropbox.width), float(page.cropbox.height)
            if page.rotation % 180:
                width, height = height, width
            if min(width, height) <= 0 or max(width, height) > 14400:
                raise ValueError("Nicht unterstützte Seitengröße.")
            pages.append({"width": width, "height": height,
                          "mode": "split" if width > height * 1.15 else "whole",
                          "cut": 0.5, "rotation": 0})
        return pages


def validate_choices(choices, count):
    if not isinstance(choices, list) or len(choices) != count:
        raise ValueError("Die Auswahl passt nicht zur Anzahl der Scan-Seiten.")
    normalized = []
    for choice in choices:
        if not isinstance(choice, dict) or choice.get("mode") not in MODES:
            raise ValueError("Ungültige Seitenauswahl.")
        cut = choice.get("cut", 0.5)
        rotation = choice.get("rotation", 0)
        if isinstance(cut, bool) or not isinstance(cut, (int, float)) or not 0.1 <= cut <= 0.9:
            raise ValueError("Die Trennlinie muss zwischen 10 und 90 Prozent liegen.")
        if type(rotation) is not int or rotation not in (0, 90, 180, 270):
            raise ValueError("Ungültige Seitendrehung.")
        normalized.append({"mode": choice["mode"], "cut": float(cut), "rotation": rotation})
    if not any(c["mode"] != "skip" for c in normalized):
        raise ValueError("Mindestens eine Seite muss erhalten bleiben.")
    return normalized


def output_count(choices):
    return sum(2 if c["mode"] == "split" else 0 if c["mode"] == "skip" else 1 for c in choices)


def parts(page, choice):
    # Rotation normalization rewrites streams; attach to an owner first (pypdf >= 6).
    owner = PdfWriter()
    page = owner.add_page(page)
    if choice["rotation"]:
        page.rotate(choice["rotation"])
    page.transfer_rotation_to_content()
    x0, y0, x1, y1 = map(float, page.cropbox)
    mid = x0 + (x1 - x0) * choice["cut"]
    left, right = (x0, y0, mid, y1), (mid, y0, x1, y1)
    clips = {"whole": [(x0, y0, x1, y1)], "split": [left, right],
             "left": [left], "right": [right], "skip": []}[choice["mode"]]
    for clip in clips:
        part = copy.copy(page)
        part.cropbox = RectangleObject(clip)
        part.trimbox = RectangleObject(clip)
        width, height = clip[2] - clip[0], clip[3] - clip[1]
        scale = min(A4[0] / width, A4[1] / height)
        dx = (A4[0] - width * scale) / 2 - clip[0] * scale
        dy = (A4[1] - height * scale) / 2 - clip[1] * scale
        target = PageObject.create_blank_page(width=A4[0], height=A4[1])
        target.merge_transformed_page(part, Transformation().scale(scale).translate(dx, dy))
        yield target


def render_preview(source, index, rotation, size, destination):
    with tempfile.TemporaryDirectory() as scratch, \
            tempfile.TemporaryDirectory(dir=Path(destination).parent) as output, \
            open(source, "rb") as stream:
        reader = PdfReader(stream)
        writer = PdfWriter()
        page = copy.copy(reader.pages[index])
        if rotation:
            page.rotate(rotation)
        writer.add_page(page)
        single = Path(scratch) / "single.pdf"
        writer.write(single)
        # Publish atomically within the data filesystem; /tmp may be a separate tmpfs.
        base = Path(output) / "preview"
        run_tool(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-scale-to", str(size),
                  "-png", str(single), str(base)], Control(), timeout=90)
        os.replace(base.with_suffix(".png"), destination)


def export_pdf(source, destination, choices, *, ocr=True, control=None, progress=None):
    control = control or Control()
    if Path(source).resolve() == Path(destination).resolve():
        raise ValueError("Das Original darf nicht überschrieben werden.")
    with open(source, "rb") as stream, tempfile.TemporaryDirectory() as scratch:
        reader = PdfReader(stream)
        if reader.is_encrypted:
            raise ValueError("Verschlüsselte PDF wird nicht unterstützt.")
        choices = validate_choices(choices, len(reader.pages))
        total = output_count(choices)
        writer = PdfWriter()
        writer.add_metadata({"/Creator": "ScanSplit", "/Title": "ScanSplit · A4-Ausgabe"})
        done = 0
        try:
            for page, choice in zip(reader.pages, choices):
                control.check()
                for target in parts(page, choice):
                    control.check()
                    if ocr:
                        single = PdfWriter()
                        single.add_page(target)
                        single_path = Path(scratch) / "single.pdf"
                        single.write(single_path)
                        base = str(Path(scratch) / "page")
                        run_tool(["pdftoppm", "-singlefile", "-f", "1", "-l", "1", "-r", "300",
                                  "-png", str(single_path), base], control)
                        run_tool(["tesseract", base + ".png", base, "-l", "deu", "--dpi", "300", "pdf"], control)
                        with open(base + ".pdf", "rb") as recognized:
                            result = PdfReader(recognized)
                            result.pages[0].scale_to(*A4)
                            writer.add_page(result.pages[0])
                    else:
                        writer.add_page(target)
                    done += 1
                    if progress:
                        progress(done, total)
            control.check()
            fd, staged = tempfile.mkstemp(prefix=".scansplit-", suffix=".pdf", dir=Path(destination).parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    writer.write(output)
                control.check()
                os.replace(staged, destination)
            finally:
                if os.path.exists(staged):
                    os.unlink(staged)
        finally:
            writer.close()
    return done

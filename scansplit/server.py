import argparse
import concurrent.futures
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

from . import __version__
from .engine import Cancelled, Control, export_pdf, inspect_pdf, output_count, render_preview, validate_choices

LOG = logging.getLogger("scansplit")
WEB = Path(__file__).resolve().parent.parent / "web"
TOKEN = re.compile(r"^[a-f0-9]{32}$")


def atomic_json(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


class State:
    def __init__(self, data_dir):
        self.data = Path(data_dir)
        self.data.mkdir(parents=True, exist_ok=True)
        self.upload_limit = int(os.environ.get("MAX_UPLOAD_MB", "250")) * 1024 * 1024
        self.max_pages = int(os.environ.get("MAX_PAGES", "400"))
        self.retention = max(1, int(os.environ.get("RETENTION_HOURS", "24"))) * 3600
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pdf-export")
        self.slots = threading.BoundedSemaphore(max(1, int(os.environ.get("MAX_QUEUED_JOBS", "4"))))
        self.render_slots = threading.BoundedSemaphore(2)
        self.lock = threading.RLock()
        self.active = {}
        self.preview_locks = {}
        self.stopping = threading.Event()
        self.ocr_available, self.ocr_message = self.detect_ocr()
        for path in self.data.glob("*/jobs/*/status.json"):
            try:
                job = json.loads(path.read_text())
                if job.get("state") in ("queued", "running", "cancelling"):
                    job.update(state="failed", message="Dienst neu gestartet. Bitte den Export erneut starten.")
                    atomic_json(path, job)
            except (OSError, ValueError):
                LOG.warning("Ungültiger gespeicherter Auftrag")
        self.clean()
        self.cleaner = threading.Thread(target=self.cleanup_loop, daemon=True)
        self.cleaner.start()

    @staticmethod
    def detect_ocr():
        if not shutil.which("tesseract"):
            return False, "Tesseract ist auf diesem Server nicht installiert. OCR ausschalten oder Installation prüfen."
        try:
            result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=15)
            if result.returncode or "deu" not in result.stdout.split():
                return False, "Die deutschen OCR-Sprachdaten (deu) fehlen."
        except (OSError, subprocess.TimeoutExpired):
            return False, "Tesseract konnte nicht gestartet werden."
        return True, "Deutsche Texterkennung ist verfügbar."

    def document(self, ident):
        if not TOKEN.fullmatch(ident):
            raise APIError(404, "Dokument nicht gefunden.")
        path = self.data / ident
        if not (path / "meta.json").is_file():
            raise APIError(404, "Dokument nicht mehr vorhanden. Bitte die PDF erneut hochladen.")
        return path

    def metadata(self, ident):
        return json.loads((self.document(ident) / "meta.json").read_text())

    def status_path(self, ident, job_id):
        if not TOKEN.fullmatch(job_id):
            raise APIError(404, "Auftrag nicht gefunden.")
        path = self.document(ident) / "jobs" / job_id / "status.json"
        if not path.is_file():
            raise APIError(404, "Auftrag nicht gefunden.")
        return path

    def job_status(self, ident, job_id):
        return json.loads(self.status_path(ident, job_id).read_text())

    def start_job(self, ident, payload):
        meta = self.metadata(ident)
        choices = validate_choices(payload.get("choices"), len(meta["pages"]))
        ocr = payload.get("ocr", True)
        if type(ocr) is not bool:
            raise ValueError("OCR muss aktiviert oder deaktiviert sein.")
        if ocr and not self.ocr_available:
            raise APIError(422, self.ocr_message)
        with self.lock:
            if any(doc == ident for doc, _ in self.active):
                raise APIError(409, "Für dieses Dokument läuft bereits ein Export.")
            if not self.slots.acquire(blocking=False):
                raise APIError(429, "Die Warteschlange ist voll. Bitte später erneut versuchen.")
            job_id = uuid.uuid4().hex
            folder = self.document(ident) / "jobs" / job_id
            try:
                folder.mkdir(parents=True)
                job = {"id": job_id, "state": "queued", "done": 0, "total": output_count(choices),
                       "ocr": ocr, "created_at": time.time(), "message": "Wartet auf Verarbeitung …"}
                atomic_json(folder / "status.json", job)
                control = Control()
                self.active[(ident, job_id)] = control
                self.executor.submit(self.process, ident, job_id, choices, ocr, control)
            except Exception:
                self.active.pop((ident, job_id), None)
                self.slots.release()
                raise
        return job

    def process(self, ident, job_id, choices, ocr, control):
        folder = self.document(ident) / "jobs" / job_id
        path = folder / "status.json"
        job = json.loads(path.read_text())
        def update(**fields):
            job.update(fields)
            atomic_json(path, job)
        try:
            control.check()
            update(state="running", message="Deutsche OCR wird vorbereitet …" if ocr else "PDF wird geteilt …")
            export_pdf(self.document(ident) / "source.pdf", folder / "result.pdf", choices,
                       ocr=ocr, control=control,
                       progress=lambda done, total: update(done=done, total=total, message=f"Seite {done} von {total} verarbeitet"))
            update(state="completed", message="Die A4-PDF ist fertig.", finished_at=time.time())
        except Cancelled:
            update(state="cancelled", message="Export abgebrochen. Du kannst die Einstellungen anpassen und neu starten.")
        except Exception as error:
            LOG.exception("Export fehlgeschlagen")
            update(state="failed", message=str(error)[:2000])
        finally:
            with self.lock:
                self.active.pop((ident, job_id), None)
            self.slots.release()

    def cancel(self, ident, job_id):
        path = self.status_path(ident, job_id)
        with self.lock:
            control = self.active.get((ident, job_id))
            if control:
                control.event.set()
        return json.loads(path.read_text())

    def clean(self):
        with self.lock:
            active_docs = {ident for ident, _ in self.active}
            for path in self.data.iterdir():
                if not path.is_dir() or not TOKEN.fullmatch(path.name) or path.name in active_docs:
                    continue
                try:
                    meta_path = path / "meta.json"
                    expires = json.loads(meta_path.read_text())["expires_at"] if meta_path.exists() else path.stat().st_mtime + 3600
                    if expires < time.time():
                        shutil.rmtree(path)
                        self.preview_locks.pop(path.name, None)
                except (OSError, ValueError, KeyError):
                    LOG.warning("Alte Datei konnte nicht bereinigt werden")

    def cleanup_loop(self):
        while not self.stopping.wait(1800):
            self.clean()

    def close(self):
        self.stopping.set()
        with self.lock:
            for control in self.active.values():
                control.event.set()
        self.executor.shutdown(wait=True)


class Handler(BaseHTTPRequestHandler):
    server_version = "ScanSplit"
    state: State

    def log_message(self, fmt, *args):
        # Do not put document capability URLs or original filenames in access logs.
        LOG.debug("HTTP %s", args[1] if len(args) > 1 else "")

    def headers_common(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header("Cache-Control", "no-store")

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status); self.headers_common()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body))); self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, content_type, download=None):
        with open(path, "rb") as source:
            self.send_response(200); self.headers_common()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(os.fstat(source.fileno()).st_size))
            if download:
                self.send_header("Content-Disposition", "attachment; filename=ScanSplit_A4.pdf; filename*=UTF-8''" + quote(download))
            self.end_headers(); shutil.copyfileobj(source, self.wfile)

    def payload(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Ungültige Anfrage.")
        if not 0 < length <= 256 * 1024:
            raise APIError(413, "Die Anfrage ist zu groß oder leer.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Ungültiges Datenformat.")
        return data

    def origin_check(self):
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlsplit(origin)
            if parsed.scheme not in ("http", "https") or parsed.netloc != self.headers.get("Host"):
                raise APIError(403, "Diese Anfrage stammt nicht von der ScanSplit-Oberfläche.")

    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def do_DELETE(self):
        self.dispatch("DELETE")

    def dispatch(self, method):
        try:
            self.connection.settimeout(180)
            if method != "GET":
                self.origin_check()
            self.route(method)
        except APIError as error:
            self.send_json(error.status, {"error": error.message})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)[:400]})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except FileNotFoundError:
            self.send_json(404, {"error": "Datei nicht mehr vorhanden."})
        except Exception:
            LOG.exception("Anfrage fehlgeschlagen")
            self.send_json(500, {"error": "Die Verarbeitung ist fehlgeschlagen. Bitte Serverprotokoll prüfen."})

    def route(self, method):
        parsed = urlsplit(self.path)
        path = parsed.path
        static = {"/": ("index.html", "text/html; charset=utf-8"),
                  "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/style.css": ("style.css", "text/css; charset=utf-8"),
                  "/assets/icon.png": ("assets/icon.png", "image/png"),
                  "/favicon.png": ("favicon.png", "image/png")}
        if method == "GET" and path in static:
            name, mime = static[path]; return self.send_file(WEB / name, mime)
        if method == "GET" and path == "/api/health":
            return self.send_json(200, {"ok": True, "version": __version__, "revision": os.environ.get("SCANSPLIT_REVISION", "local")[:12],
                "ocr_available": self.state.ocr_available, "ocr_message": self.state.ocr_message,
                "renderer_available": bool(shutil.which("pdftoppm")), "max_upload_mb": self.state.upload_limit // (1024 * 1024)})
        if method == "POST" and path == "/api/documents":
            return self.upload()
        fields = path.strip("/").split("/")
        if len(fields) < 3 or fields[:2] != ["api", "documents"]:
            raise APIError(404, "Nicht gefunden.")
        ident = fields[2]
        folder = self.state.document(ident)
        if len(fields) == 3:
            if method == "GET":
                return self.send_json(200, self.state.metadata(ident))
            if method == "DELETE":
                with self.state.lock:
                    if any(doc == ident for doc, _ in self.state.active):
                        raise APIError(409, "Bitte zuerst den laufenden Export abbrechen.")
                    shutil.rmtree(folder)
                    self.state.preview_locks.pop(ident, None)
                return self.send_json(200, {"deleted": True})
        if method == "GET" and len(fields) == 5 and fields[3] == "preview":
            if not fields[4].isdigit():
                raise APIError(404, "Seite nicht gefunden.")
            index = int(fields[4]); meta = self.state.metadata(ident)
            if not 0 <= index < len(meta["pages"]):
                raise APIError(404, "Seite nicht gefunden.")
            query = parse_qs(parsed.query)
            rotation = int(query.get("rotation", ["0"])[0])
            size = 240 if query.get("kind") == ["thumb"] else 1400
            if rotation not in (0, 90, 180, 270):
                raise ValueError("Ungültige Drehung.")
            destination = folder / "previews" / f"{index}-{rotation}-{size}.png"
            with self.state.lock:
                lock = self.state.preview_locks.setdefault(ident, threading.Lock())
            with lock, self.state.render_slots:
                if not destination.is_file():
                    destination.parent.mkdir(exist_ok=True)
                    render_preview(folder / "source.pdf", index, rotation, size, destination)
                return self.send_file(destination, "image/png")
        if len(fields) == 4 and fields[3] == "jobs" and method == "POST":
            return self.send_json(202, self.state.start_job(ident, self.payload()))
        if len(fields) >= 5 and fields[3] == "jobs":
            job_id = fields[4]
            job = self.state.job_status(ident, job_id)
            if len(fields) == 5 and method == "GET":
                return self.send_json(200, job)
            if len(fields) == 6 and fields[5] == "cancel" and method == "POST":
                return self.send_json(200, self.state.cancel(ident, job_id))
            if len(fields) == 6 and fields[5] == "result.pdf" and method == "GET":
                if job["state"] != "completed":
                    raise APIError(409, "Die PDF ist noch nicht fertig.")
                name = Path(self.state.metadata(ident)["name"]).stem + "_A4.pdf"
                return self.send_file(folder / "jobs" / job_id / "result.pdf", "application/pdf", name)
        raise APIError(404, "Nicht gefunden.")

    def upload(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/pdf":
            raise APIError(415, "Bitte eine PDF-Datei hochladen.")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "Ungültige Dateigröße.")
        if not 5 <= length <= self.state.upload_limit:
            raise APIError(413, f"Die PDF darf höchstens {self.state.upload_limit // (1024 * 1024)} MB groß sein.")
        ident = uuid.uuid4().hex
        folder = self.state.data / ident; folder.mkdir()
        try:
            source = folder / "source.pdf"
            with open(source, "wb") as target:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Upload wurde unterbrochen.")
                    target.write(chunk); remaining -= len(chunk)
            with open(source, "rb") as stream:
                if b"%PDF-" not in stream.read(1024):
                    raise ValueError("Die Datei ist keine gültige PDF.")
            try:
                pages = inspect_pdf(source, self.state.max_pages)
            except ValueError:
                raise
            except Exception as error:
                raise ValueError("Die PDF konnte nicht gelesen werden. Bitte eine gültige Scan-PDF auswählen.") from error
            name = unquote(self.headers.get("X-File-Name", "Scan.pdf"))
            name = re.sub(r"[\x00-\x1f\x7f]", "", name.replace("\\", "/").split("/")[-1])[:150] or "Scan.pdf"
            meta = {"id": ident, "name": name, "pages": pages, "created_at": time.time(),
                    "expires_at": time.time() + self.state.retention}
            atomic_json(folder / "meta.json", meta)
            return self.send_json(201, meta)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Check the release without starting HTTP")
    args = parser.parse_args()
    if args.check:
        for file in ("index.html", "app.js", "style.css", "assets/icon.png"):
            if not (WEB / file).is_file():
                raise SystemExit("Unvollständige ScanSplit-Version: " + file)
        if not shutil.which("pdftoppm"):
            raise SystemExit("Poppler (pdftoppm) fehlt.")
        print("ScanSplit release check OK")
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    state = State(os.environ.get("SCANSPLIT_DATA_DIR", "./data"))
    handler = type("ScanSplitHandler", (Handler,), {"state": state})
    server = ThreadingHTTPServer((os.environ.get("SCANSPLIT_HOST", "0.0.0.0"), int(os.environ.get("SCANSPLIT_PORT", "8080"))), handler)
    server.daemon_threads = True
    def stop(_signum, _frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
        state.stopping.set()
        with state.lock:
            for control in state.active.values():
                control.event.set()
    signal.signal(signal.SIGTERM, stop); signal.signal(signal.SIGINT, stop)
    LOG.info("ScanSplit %s · http://%s:%s · OCR %s", __version__, *server.server_address, state.ocr_available)
    try:
        server.serve_forever()
    finally:
        state.close(); server.server_close()

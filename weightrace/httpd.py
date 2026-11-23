from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import logging
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .codec import canonical, loads
from .errors import Problem
from .routes import PREFIX, route_api

ASSETS = Path(__file__).resolve().parent.parent / "web"
ASSET_PATH = re.compile(r"/(?:css/[a-z-]+\.css|js/[a-z-]+\.js)")
TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}
MAX_BODY = 256_000
LOG = logging.getLogger(__name__)


class WorkbenchServer(ThreadingHTTPServer):
    def __init__(self, db, port):
        self.db = db
        super().__init__(("127.0.0.1", port), WorkbenchHandler)


class WorkbenchHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def log_message(self, pattern, *args):
        LOG.debug(pattern, *args)

    def respond(self, status, payload, content_type="application/json", filename=None):
        body = canonical(payload).encode("utf-8") if content_type == "application/json" and filename is None else payload
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        if self.headers.get_content_type() != "application/json":
            raise Problem("content_type", "请求类型须为 application/json", 415)
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]) or self.headers.get("Transfer-Encoding"):
            raise Problem("content_length", "须提供有效请求长度", 411)
        size = int(lengths[0])
        if not 0 < size <= MAX_BODY:
            raise Problem("body_size", "请求体为空或超过大小上限", 413)
        self.connection.settimeout(5)
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("truncated body")
            return loads(raw)
        except (ValueError, RecursionError):
            raise Problem("json", "无法解析 UTF-8 JSON 请求") from None
        except TimeoutError:
            raise Problem("timeout", "接收请求超时", 408) from None

    def serve_asset(self, path):
        if path == "/":
            path = "/index.html"
        elif not ASSET_PATH.fullmatch(path):
            raise Problem("not_found", "页面不存在", 404)
        asset = ASSETS / path.lstrip("/")
        try:
            data = asset.read_bytes()
        except FileNotFoundError:
            raise Problem("not_found", "页面不存在", 404) from None
        self.respond(HTTPStatus.OK, data, TYPES[asset.suffix])

    def handle_request(self):
        try:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if port == 80:
                hosts.update({"127.0.0.1", "localhost"})
            host = self.headers.get("Host")
            origin = self.headers.get("Origin")
            if host not in hosts or (origin is not None and origin != f"http://{host}"):
                raise Problem("local_origin", "仅允许本机同源访问", 403)
            try:
                target = urlsplit(self.path)
            except ValueError:
                raise Problem("target", "请求路径无效") from None
            if target.scheme or target.netloc:
                raise Problem("target", "请求路径无效")
            if target.path.startswith(PREFIX):
                write = self.command == "POST"
                payload = self.read_body() if write else None
                with self.server.db.transaction(write) as db:
                    status, response = route_api(db, self.command, self.path, payload)
                if isinstance(response, tuple):
                    self.respond(status, response[0], filename=response[1])
                else:
                    self.respond(status, response)
            elif self.command == "GET":
                self.serve_asset(target.path)
            else:
                raise Problem("not_found", "接口不存在", 404)
        except Problem as exc:
            self.respond(exc.status, exc.payload())
        except (BrokenPipeError, ConnectionResetError):
            return
        except sqlite3.Error as exc:
            LOG.exception("database request failed")
            busy = getattr(exc, "sqlite_errorname", "") in {"SQLITE_BUSY", "SQLITE_LOCKED"}
            self.respond(503 if busy else 500, {"error": "storage", "message": "存储繁忙，请重试" if busy else "存储处理失败"})

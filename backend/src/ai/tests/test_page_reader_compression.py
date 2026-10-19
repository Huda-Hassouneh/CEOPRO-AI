"""Regression: a gzip-compressed page must be readable. page_reader re-wrapped the
already-decompressed body while keeping Content-Encoding: gzip, so httpx decompressed
it twice and every ordinary compressed page was reported unreachable. Uses a real local
HTTP server and the real default fetch (no mocks), which is what exposed it."""
import gzip
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from src.ai.research import page_reader

HTML = "<html><head><title>Price list</title></head><body><p>Widget costs 12 JOD.</p></body></html>"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = gzip.compress(HTML.encode())
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_default_fetch_returns_the_decompressed_body_of_a_gzip_response():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = page_reader._default_fetch(f"http://127.0.0.1:{server.server_port}/p")
    finally:
        server.shutdown()
    assert response.status_code == 200
    assert "Widget costs 12 JOD." in response.text
    assert "content-encoding" not in response.headers

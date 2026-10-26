"""Exercise Scrapy's real reactor and the security-fixed Twisted parsers."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


@pytest.mark.parametrize("separator", [b"\r", b"\n", b"\x00"])
def test_twisted_rejects_control_characters_in_header_values(separator):
    from twisted.web.http import HTTPChannel
    channel = HTTPChannel()
    rejected = []
    channel._respondToBadRequestAndDisconnect = lambda: rejected.append(True)
    assert channel.headerReceived(b"X-Test: first" + separator + b"Content-Length: 12") is False
    assert rejected == [True]


def test_imap_pattern_cannot_inject_a_regular_expression():
    from twisted.mail.imap4 import wildcardToRegexp
    pattern = wildcardToRegexp("(a+)+z", "/")
    assert pattern.fullmatch("(a+)+z")
    assert not pattern.fullmatch("a" * 32 + "z")


def test_scrapy_asyncio_reactor_fetches_and_parses_local_http(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><title>KEEL reactor compatibility</title></html>")
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    result_file = tmp_path / "result.txt"
    probe = tmp_path / "probe.py"
    probe.write_text('''import sys
from pathlib import Path
import scrapy
from scrapy.crawler import CrawlerProcess
class Probe(scrapy.Spider):
    name = "keel_twisted_compatibility"
    def start_requests(self):
        yield scrapy.Request(sys.argv[1], callback=self.parse)
    async def start(self):
        for request in self.start_requests():
            yield request
    def parse(self, response):
        Path(sys.argv[2]).write_text(response.css("title::text").get(), encoding="utf-8")
process = CrawlerProcess({"LOG_ENABLED": False, "ROBOTSTXT_OBEY": False,
    "TWISTED_REACTOR": "twisted.internet.asyncioreactor.AsyncioSelectorReactor",
    "DOWNLOAD_TIMEOUT": 5, "RETRY_ENABLED": False, "HTTPPROXY_ENABLED": False})
process.crawl(Probe)
process.start()
''', encoding="utf-8")
    try:
        result = subprocess.run([sys.executable, str(probe), f"http://127.0.0.1:{server.server_port}/", str(result_file)],
                                env=os.environ.copy(), capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert result_file.read_text(encoding="utf-8") == "KEEL reactor compatibility"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_app_and_worker_manifests_use_the_same_security_fixed_twisted():
    backend = Path(__file__).resolve().parents[3]
    for package in ("ai", "market_scraper"):
        lines = (backend / "src" / package / "requirements.txt").read_text(encoding="utf-8").splitlines()
        assert "Twisted==26.10.0rc1" in lines


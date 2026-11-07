"""Actual HTTP download + DNS/pinning + parsing; only fixture socket routing differs.

The public test hostname resolves to a public address under the real security
policy. A test-only httpcore socket route connects it to our loopback server.
No production allow-private flag or extractor/parser replacement is used.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
import socket
from threading import Thread
from unittest.mock import patch

from httpcore._backends.sync import SyncBackend

from src.ai.marketing import url_extractor
from src.market_scraper.network_security import pin_request


@contextmanager
def controlled_product_page():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            body = (b'<html><head><script type="application/ld+json">'
                    b'{"@context":"https://schema.org","@graph":[{"@type":"Product",'
                    b'"name":"ControlledFixtureCup","description":"CONTROLLED_HTTP_FIXTURE: a 330 ml cup.",'
                    b'"offers":{"price":"19.99","priceCurrency":"JOD"}}]}</script></head><body>Fixture</body></html>')
            if self.path == '/og':
                body = b'<html><head><meta property="og:title" content="Actual OG cup"><meta property="og:description" content="A blue cup"></head></html>'
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_dns, original_connect = socket.getaddrinfo, SyncBackend.connect_tcp
    def resolve(host, *args, **kwargs):
        if host == 'catalog.keel-fixture.test':
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', port))]
        return original_dns(host, *args, **kwargs)
    def connect(backend, host, port, *args, **kwargs):
        if host == '1.1.1.1' and port == server.server_address[1]:
            host = '127.0.0.1'
        return original_connect(backend, host, port, *args, **kwargs)
    try:
        no_proxy = ','.join(filter(None, [os.environ.get('NO_PROXY'), '1.1.1.1', 'catalog.keel-fixture.test']))
        with patch.dict(os.environ, {'NO_PROXY': no_proxy, 'CONNECTORS_ALLOW_PRIVATE_HOSTS': 'false'}), patch.object(socket, 'getaddrinfo', resolve), \
             patch.object(url_extractor, 'pin_request', lambda url: pin_request(url, resolver=resolve)), \
             patch.object(SyncBackend, 'connect_tcp', connect):
            yield f'http://catalog.keel-fixture.test:{port}', requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_http_jsonld_graph_download_and_extraction():
    with controlled_product_page() as (base, requests):
        result = url_extractor.extract_product_info_from_url(base+'/product')
    assert requests == ['/product']
    assert result.name == 'ControlledFixtureCup'
    assert result.price == '19.99 JOD'
    assert '330 ml' in result.as_text()


def test_real_http_opengraph_shape_without_title_fallback():
    with controlled_product_page() as (base, requests):
        result = url_extractor.extract_product_info_from_url(base+'/og')
    assert requests == ['/og']
    assert result.name == 'Actual OG cup' and result.description == 'A blue cup'

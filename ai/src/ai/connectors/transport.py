"""Bounded HTTPS GET, pinned public DNS, verified TLS, no redirects/proxies."""
import http.client
import json
import socket
import ssl
from urllib.parse import urlsplit
from src.market_scraper.network_security import resolve_public_addresses
from src.ai.connectors.response_text import decode_document

class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

class PublicConnection(http.client.HTTPSConnection):
    def connect(self):
        addresses = resolve_public_addresses('https://' + self.host)
        last = None
        for address in sorted(addresses):
            try:
                connection = socket.create_connection((address, self.port), self.timeout)
                try:
                    self.sock = self._context.wrap_socket(connection, server_hostname=self.host)
                except Exception:
                    connection.close()
                    raise
                return
            except OSError as exc:
                last = exc
        raise last or ProviderError('STORE_UNREACHABLE')

def get_json(url, authorization=None):
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password or not parsed.hostname:
        raise ProviderError('INVALID_STORE_URL')
    connection = PublicConnection(parsed.hostname, timeout=15, context=ssl.create_default_context())
    try:
        headers = {'Accept': 'application/json', 'User-Agent': 'KEEL-StoreConnector/1.0'}
        if authorization:
            headers['Authorization'] = authorization
        connection.request('GET', parsed.path + ('?' + parsed.query if parsed.query else ''), headers=headers)
        response = connection.getresponse()
        if response.status in (401, 403):
            raise ProviderError('STORE_ACCESS_DENIED')
        if response.status != 200:
            raise ProviderError('STORE_RESPONSE_ERROR')
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ProviderError('STORE_RESPONSE_TOO_LARGE')
        return json.loads(decode_document(body, 2 * 1024 * 1024)), dict(response.getheaders())
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('STORE_UNREACHABLE') from None
    finally:
        connection.close()

def post_json(url, payload, headers=None):
    """Same public-network boundary as GET; credentials never appear in the URL."""
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password or not parsed.hostname:
        raise ProviderError('INVALID_STORE_URL')
    connection = PublicConnection(parsed.hostname, timeout=20, context=ssl.create_default_context())
    try:
        request_headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'KEEL-StoreConnector/1.0', **(headers or {})}
        connection.request('POST', parsed.path, body=json.dumps(payload).encode(), headers=request_headers)
        response = connection.getresponse()
        if response.status in (401, 403):
            raise ProviderError('STORE_ACCESS_DENIED')
        if response.status == 429:
            raise ProviderError('STORE_RATE_LIMITED')
        if response.status != 200:
            raise ProviderError('STORE_RESPONSE_ERROR')
        body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ProviderError('STORE_RESPONSE_TOO_LARGE')
        return json.loads(decode_document(body, 2 * 1024 * 1024))
    except ProviderError:
        raise
    except Exception:
        raise ProviderError('STORE_UNREACHABLE') from None
    finally:
        connection.close()

"""Isolated review checker tests using the real worker parser, no network/DB."""
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
AI = Path(os.environ.get('MARKET_AI_CODEBASE_PATH', ROOT.parent / 'ai'))
sys.path.insert(0, str(AI))
spec = importlib.util.spec_from_file_location('source_check', ROOT / 'scripts/competitor-source-check.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class Response(io.BytesIO):
    status = 200


class SourceCheckTests(unittest.TestCase):
    def check(self, urls, robots=b'User-agent: *\nAllow: /\n', error=None):
        calls = []
        class Opener:
            def open(self, req, timeout):
                calls.append(req)
                if error:
                    raise error
                return Response(robots)
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))]
        with patch('socket.getaddrinfo', return_value=answers), patch('urllib.request.build_opener', return_value=Opener()):
            result = checker.check(urls)
        return result, calls

    def test_real_parser_allows_product_but_denies_internal_search(self):
        robots=b'User-agent: *\n\n# Realistic blank line\nDisallow: /*?s=\nAllow: /product/\n'
        result, calls = self.check(['https://market.example/product/tea'], robots)
        self.assertEqual(result['allowed'], True)
        from src.market_scraper.settings import USER_AGENT
        self.assertEqual(calls[0].get_header('User-agent'), USER_AGENT)
        self.assertEqual(calls[0].full_url, 'https://market.example/robots.txt')
        result, calls = self.check(['https://market.example/product/tea','https://market.example/?s=tea'], robots)
        self.assertEqual(result, {'allowed':False,'reason':'ROBOTS_DISALLOWED'})
        self.assertEqual(len(calls), 1, 'One robots fetch covers all paths on the source')

    def test_unknown_and_blocked_http_are_not_approvals(self):
        for status in [301,302,401,403,429,500]:
            result, _ = self.check(['https://market.example/product/tea'],error=urllib.error.HTTPError('https://market.example/robots.txt',status,'denied',{},None))
            self.assertEqual(result['allowed'], None)
        result, _ = self.check(['https://market.example/product/tea'], robots=b'<html>Challenge</html>')
        self.assertEqual(result['allowed'], None)

    def test_absent_robots_uses_existing_worker_contract(self):
        result, _ = self.check(['https://market.example/product/tea'],error=urllib.error.HTTPError('https://market.example/robots.txt',404,'absent',{},None))
        self.assertEqual(result['allowed'],True)

    def test_private_targets_mixed_origins_and_limits_fail_closed(self):
        answers=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('socket.getaddrinfo',return_value=answers):
            self.assertEqual(checker.check(['https://market.example/product/tea'])['reason'],'UNSAFE_TARGET')
        self.assertEqual(self.check(['https://market.example/product/tea','https://other.example/product/tea'])[0]['reason'],'SOURCE_HOST_MISMATCH')
        self.assertEqual(checker.check([])['allowed'],None)
        self.assertEqual(checker.check(['https://market.example/product/tea']*101)['reason'],'TOO_MANY_PATHS')

    def test_no_redirect_handler_or_proxy_bypass(self):
        captured=[]
        class Opener:
            def open(self, req, timeout):
                return Response(b'User-agent: *\nAllow: /\n')
        def build(*handlers):
            captured.extend(handlers)
            return Opener()
        answers=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        with patch('socket.getaddrinfo',return_value=answers),patch('urllib.request.build_opener',side_effect=build):
            self.assertTrue(checker.check(['https://market.example/product/tea'])['allowed'])
        redirect=next(h for h in captured if isinstance(h,checker.urllib.request.HTTPRedirectHandler))
        self.assertIsNone(redirect.redirect_request(None,None,302,'',{},'http://127.0.0.1/private'))
        proxy=next(h for h in captured if isinstance(h,checker.urllib.request.ProxyHandler))
        self.assertEqual(proxy.proxies,{})

    def test_socket_dns_rebinding_is_rejected(self):
        # A public preflight followed by a private answer at connection time.
        answers=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        private=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        class Opener:
            def open(self, req, timeout):
                socket.getaddrinfo('market.example',443,type=socket.SOCK_STREAM)
                return Response(b'User-agent: *\nAllow: /\n')
        with patch('socket.getaddrinfo',side_effect=[answers,answers,private]),patch('urllib.request.build_opener',return_value=Opener()):
            self.assertIsNone(checker.check(['https://market.example/product/tea'])['allowed'])


if __name__ == '__main__':
    unittest.main()

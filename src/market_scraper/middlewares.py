"""Scrapy downloader middleware enforcing network boundaries on every hop."""

from src.market_scraper.network_security import resolve_public_addresses, validate_same_origin


class PublicNetworkBoundaryMiddleware:
    """Reject private DNS answers and cross-origin requests/responses, including redirects."""

    def process_request(self, request, spider):
        approved = self._approved_host(spider)
        validate_same_origin(request.url, approved)
        resolve_public_addresses(request.url)
        return None

    def process_response(self, request, response, spider):
        approved = self._approved_host(spider)
        validate_same_origin(response.url, approved)
        resolve_public_addresses(response.url)
        return response

    @staticmethod
    def _approved_host(spider):
        domains = getattr(spider, "allowed_domains", [])
        if len(domains) != 1:
            raise ValueError("market spiders require exactly one approved host")
        return domains[0]

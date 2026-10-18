from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ProductContext:
    """What a provider needs to look one product up."""
    product_id: str
    name: str
    country_code: Optional[str] = None   # the tenant's market, ISO-3166 alpha-2
    currency: Optional[str] = None       # the tenant's own currency (fallback when a listing shows none)
    your_price: Optional[float] = None
    barcode: Optional[str] = None        # EAN/UPC/GTIN from products.metadata (barcode | gtin | ean), when the owner recorded one


@dataclass(frozen=True)
class PriceQuote:
    """One price for the product, as a source stated it."""
    provider: str
    title: str
    price: float
    currency: str
    seller: Optional[str] = None
    url: Optional[str] = None
    rating: Optional[float] = None       # 0-5
    review_count: Optional[int] = None
    observed_on: Optional[str] = None    # ISO date the source says the price was seen (None = just now)


class ProviderUnavailable(Exception):
    """The provider is not set up here (missing key / search provider)."""


class ProviderError(Exception):
    """The provider is set up but the call failed (network, quota, bad answer)."""

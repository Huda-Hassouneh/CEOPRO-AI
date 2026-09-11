"""
CEOPRO AI - Proximity math for region-aware competitor discovery.

Pure stdlib great-circle distance (haversine) - no geocoding API, no new
dependency. This module never resolves an address into coordinates; it
only measures the distance between two coordinate pairs a caller already
has (from companies.latitude/longitude, global_competitors.latitude/
longitude, or a discovery source like Google Places that returns real
geometry.location). Feeding it an address string is a caller bug, not
something this module tries to paper over.
"""
import math
from typing import Optional

_EARTH_RADIUS_KM = 6371.0088  # IUGG mean earth radius - standard haversine constant


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two WGS84 coordinate pairs."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def distance_km_if_known(
    lat1: Optional[float], lon1: Optional[float], lat2: Optional[float], lon2: Optional[float],
) -> Optional[float]:
    """
    None whenever any coordinate is missing - never a fabricated or
    zero-by-default distance. This is the honest "unknown, not computed"
    outcome the same convention as _in_operating_region()'s handling of an
    unknown competitor country: absence of evidence, not evidence of
    absence, so the caller must not silently treat None as 0km/nearby.
    """
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None
    return haversine_km(lat1, lon1, lat2, lon2)

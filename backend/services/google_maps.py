"""
Google Maps Places scraper — ported and optimised from the MAD MAX n8n workflow.

Two workflows in one:
  Generate Parcels  → geocode → generate viewports → loop over centers → call Get Businesses
  Get Businesses    → Places API per viewport → paginate via nextPageToken → save results

Key corrections vs. original implementation:
  - 8 outer centers (not 5) — all cardinal + diagonal directions, matching the real n8n JSON
  - nextPageToken pagination — each viewport can yield up to 3 pages × 20 = 60 results
  - max_items cap — stop collecting once the limit is reached
  - nextPageToken included in FieldMask (required for pagination)

Max theoretical yield per Deep Sweep:
  9 centers × 36 viewports × 60 results = 19,440 raw results before deduplication
"""

import math
import asyncio
import httpx
from typing import Optional, Callable
from urllib.parse import urlparse

PLACES_NEW_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# Field mask — matches n8n workflow exactly, includes nextPageToken for pagination
FIELD_MASK = (
    "places.displayName,places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.websiteUri,places.formattedAddress,places.id,"
    "places.rating,places.userRatingCount,places.types,places.googleMapsUri,"
    "nextPageToken"
)

METERS_PER_DEG_LAT = 111320


# ── Utilities ─────────────────────────────────────────────────────────

def _extract_domain(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    try:
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.replace("www.", "")
        return domain if domain else None
    except Exception:
        return None


def _place_to_dict(place: dict) -> dict:
    website = place.get("websiteUri")
    name = place.get("displayName", {}).get("text", "")
    types = place.get("types", [])
    return {
        "google_place_id": place.get("id", ""),
        "business_name": name,
        "address": place.get("formattedAddress"),
        "phone": place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber"),
        "website": website,
        "domain": _extract_domain(website),
        "category": ", ".join(types[:3]),
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
        "maps_url": place.get("googleMapsUri") or "",
    }


# ── Geocoding ─────────────────────────────────────────────────────────

async def geocode_location(location: str, api_key: str) -> tuple[float, float]:
    """Convert a location string to (lat, lon) using Places API text search — no Geocoding API needed."""
    payload = {"textQuery": location, "maxResultCount": 1}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.location.latitude,places.location.longitude",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(PLACES_NEW_SEARCH_URL, json=payload, headers=headers)
        if not resp.is_success:
            raise ValueError(f"Geocode failed ({resp.status_code}): {resp.text}")
        data = resp.json()

    places = data.get("places", [])
    if not places or "location" not in places[0]:
        raise ValueError(f"Could not geocode '{location}': no results from Places API")

    loc = places[0].get("location", {})
    if "latitude" not in loc:
        raise ValueError(f"Could not geocode '{location}': no location in response")
    return loc["latitude"], loc["longitude"]


# ── Grid generation ───────────────────────────────────────────────────

def _offset_to_latlon(lat_a: float, lon_a: float, x_m: float, y_m: float) -> dict:
    """Convert meter offsets to lat/lon — mirrors n8n's offsetToLatLon()."""
    lat_rad = lat_a * math.pi / 180
    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(lat_rad)
    return {
        "latitude": lat_a + (y_m / METERS_PER_DEG_LAT),
        "longitude": lon_a + (x_m / meters_per_deg_lon),
    }


def generate_viewports(lat_a: float, lon_a: float, square_size: float) -> list[dict]:
    """
    Generate 36 viewport rectangles from a center point.
    Mirrors n8n's Generate Viewports / Generate Viewports1 nodes exactly.
    square_size in meters.
    """
    a = float(square_size)

    pts = {
        "A": [0, 0],
        "B": [a, a],     "C": [a, -a],    "D": [-a, a],    "E": [-a, -a],
        "F": [2*a, 0],   "G": [2*a, 2*a], "H": [0, 2*a],   "I": [-2*a, 2*a],
        "J": [-2*a, 0],  "K": [-2*a, -2*a], "L": [0, -2*a], "M": [2*a, -2*a],
        "N": [3*a, a],   "O": [3*a, 3*a],  "P": [a, 3*a],   "Q": [-a, 3*a],
        "R": [-3*a, 3*a], "S": [-3*a, a],  "T": [-3*a, -a], "U": [-3*a, -3*a],
        "V": [-a, -3*a], "W": [a, -3*a],   "X": [3*a, -3*a], "Y": [3*a, -a],
    }

    geo = {name: _offset_to_latlon(lat_a, lon_a, x, y) for name, (x, y) in pts.items()}

    pairs = [
        "RI", "IQ", "QH", "HP", "PG", "GO",
        "SI", "ID", "DH", "HB", "BG", "GN",
        "SJ", "JD", "DA", "AB", "BF", "FN",
        "TJ", "JE", "EA", "AC", "CF", "FY",
        "TK", "KE", "EL", "LC", "CM", "MY",
        "UK", "KV", "VL", "LW", "WM", "MX",
    ]

    viewports = []
    for pair in pairs:
        p1 = geo[pair[0]]
        p2 = geo[pair[1]]
        viewports.append({
            "low": {
                "latitude":  min(p1["latitude"],  p2["latitude"]),
                "longitude": min(p1["longitude"], p2["longitude"]),
            },
            "high": {
                "latitude":  max(p1["latitude"],  p2["latitude"]),
                "longitude": max(p1["longitude"], p2["longitude"]),
            },
        })

    return viewports


def generate_outer_centers(lat_a: float, lon_a: float, square_size: float) -> list[dict]:
    """
    Generate 8 outer sweep centers — mirrors n8n's Generate New CentrePoints node.

    The real n8n JSON uses ALL 8 directions (the earlier pasted snippet had
    some commented out, but the actual workflow JSON includes all 8).

    Spacing = 3 * 2 * square_size = 6 × square_size so grids tile with no gaps.
    """
    a = 3 * 2 * float(square_size)

    offsets = [
        (a,  0),   # middle-right
        (a,  a),   # top-right
        (0,  a),   # top-middle
        (-a, a),   # top-left
        (-a, 0),   # middle-left
        (-a, -a),  # bottom-left
        (0,  -a),  # bottom-middle
        (a,  -a),  # bottom-right
    ]

    return [_offset_to_latlon(lat_a, lon_a, x, y) for x, y in offsets]


# ── Places API — single viewport with pagination ──────────────────────

async def _search_viewport_all_pages(
    client: httpx.AsyncClient,
    keyword: str,
    viewport: dict,
    api_key: str,
) -> list[dict]:
    """
    Mirrors n8n's Get Businesses workflow:
    - Fetches first page for this viewport
    - Follows nextPageToken recursively until exhausted
    - Returns all places found across all pages for this viewport
    """
    results = []
    page_token: Optional[str] = None
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }

    while True:
        payload: dict = {
            "textQuery": keyword,
            "locationRestriction": {"rectangle": viewport},
            "maxResultCount": 20,
        }
        if page_token:
            payload["pageToken"] = page_token

        try:
            resp = await client.post(PLACES_NEW_SEARCH_URL, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            break  # best-effort — skip failed pages

        places = data.get("places", [])
        if not places:
            break

        for place in places:
            results.append(_place_to_dict(place))

        page_token = data.get("nextPageToken")
        if not page_token:
            break

        # Google requires a short delay before using nextPageToken
        await asyncio.sleep(2)

    return results


# ── Grid search — single center, 36 viewports ─────────────────────────

async def _search_all_viewports(
    keyword: str,
    lat: float,
    lon: float,
    square_size: float,
    api_key: str,
    max_items: int,
    seen_ids: set,
    progress_callback: Optional[Callable] = None,
    viewport_offset: int = 0,
    total_viewports: int = 36,
) -> list[dict]:
    """Search all 36 viewports for one center point, with pagination."""
    viewports = generate_viewports(lat, lon, square_size)
    results = []

    async with httpx.AsyncClient() as client:
        for i, viewport in enumerate(viewports):
            if max_items > 0 and len(seen_ids) >= max_items:
                break

            pages = await _search_viewport_all_pages(
                client, keyword, viewport, api_key,
            )

            for biz in pages:
                pid = biz.get("google_place_id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    results.append(biz)

            if progress_callback:
                await progress_callback(viewport_offset + i + 1, total_viewports, len(seen_ids))

    return results


# ── Public API ────────────────────────────────────────────────────────

async def grid_search_businesses(
    keyword: str,
    location: str,
    api_key: str,
    square_size: float = 2000,
    max_items: int = 0,
    progress_callback: Optional[Callable] = None,
) -> list[dict]:
    """
    Area Sweep — 1 center, 36 viewports, paginated.
    Up to 36 × 60 = 2,160 results before deduplication.
    """
    lat, lon = await geocode_location(location, api_key)
    seen_ids: set = set()

    results = await _search_all_viewports(
        keyword, lat, lon, square_size, api_key, max_items,
        seen_ids, progress_callback,
        viewport_offset=0, total_viewports=36,
    )
    return results


async def deep_search_businesses(
    keyword: str,
    location: str,
    api_key: str,
    square_size: float = 2000,
    max_items: int = 0,
    progress_callback: Optional[Callable] = None,
) -> list[dict]:
    """
    Deep Sweep — 9 centers × 36 viewports, paginated.
    Mirrors the full Generate Parcels + Get Businesses n8n workflow.

    Centers: 1 origin + 8 outer ring (all 8 directions as in the real n8n JSON).
    Up to 9 × 36 × 60 = 19,440 results before deduplication.
    """
    lat, lon = await geocode_location(location, api_key)

    outer = generate_outer_centers(lat, lon, square_size)
    centers = [{"latitude": lat, "longitude": lon}] + outer  # 9 total

    total_viewports = len(centers) * 36  # 324

    seen_ids: set = set()
    all_results: list[dict] = []

    for center_idx, center in enumerate(centers):
        if max_items > 0 and len(seen_ids) >= max_items:
            break

        batch = await _search_all_viewports(
            keyword,
            center["latitude"],
            center["longitude"],
            square_size,
            api_key,
            max_items,
            seen_ids,
            progress_callback,
            viewport_offset=center_idx * 36,
            total_viewports=total_viewports,
        )
        all_results.extend(batch)

    return all_results


# ── Quick search (single text query, original Places API) ─────────────

async def search_businesses(keyword: str, location: str, api_key: str, max_results: int = 60) -> list[dict]:
    """Quick search — single text query, up to 60 results. No grid."""
    results = []
    next_page_token = None

    async with httpx.AsyncClient(timeout=30) as client:
        while len(results) < max_results:
            params = {"query": f"{keyword} in {location}", "key": api_key}
            if next_page_token:
                params = {"pagetoken": next_page_token, "key": api_key}

            resp = await client.get(PLACES_TEXT_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") not in ("OK", "ZERO_RESULTS"):
                raise ValueError(f"Maps API error: {data.get('status')} — {data.get('error_message', '')}")

            for place in data.get("results", []):
                website = place.get("website")
                results.append({
                    "google_place_id": place.get("place_id"),
                    "business_name": place.get("name"),
                    "address": place.get("formatted_address"),
                    "website": website,
                    "domain": _extract_domain(website),
                    "phone": place.get("formatted_phone_number"),
                    "category": ", ".join(place.get("types", [])[:3]),
                    "rating": place.get("rating"),
                    "review_count": place.get("user_ratings_total"),
                    "maps_url": f"https://maps.google.com/?cid={place.get('place_id')}",
                })
                if len(results) >= max_results:
                    break

            next_page_token = data.get("next_page_token")
            if not next_page_token:
                break

    return results

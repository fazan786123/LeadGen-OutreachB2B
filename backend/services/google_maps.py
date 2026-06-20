"""
Viewport grid scraper — ported from the MAD MAX n8n workflow.

Algorithm:
  1. Geocode the city name → center lat/lon
  2. Generate 25 grid points (A–Y) spaced `square_size` meters apart
  3. Build 36 diagonal viewport pairs — each pair = a search rectangle
  4. Hit Google Places API (New) searchText for each viewport
  5. Deduplicate by place_id and return

With square_size=2000m the grid covers a ~12×12km area (most cities).
With square_size=5000m it covers ~30×30km (metro areas).

36 viewports × up to 20 results each = up to 720 raw results before deduplication.
"""

import math
import httpx
from typing import Optional
from urllib.parse import urlparse

# ── Old Places API (used for quick search) ────────────────────────────
PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

# ── New Places API (used for viewport/grid search) ────────────────────
PLACES_NEW_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

NEW_API_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.nationalPhoneNumber,"
    "places.rating,places.userRatingCount,places.types,places.googleMapsUri"
)

METERS_PER_DEG_LAT = 111320


def _extract_domain(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    try:
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.replace("www.", "")
        return domain if domain else None
    except Exception:
        return None


# ── Geocoding ─────────────────────────────────────────────────────────

async def geocode_location(location: str, api_key: str) -> tuple[float, float]:
    """Convert a location string to (lat, lon)."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(GEOCODE_URL, params={"address": location, "key": api_key})
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "OK" or not data.get("results"):
        raise ValueError(f"Could not geocode '{location}': {data.get('status')}")

    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


# ── Grid generation (exact port of n8n algorithm) ─────────────────────

def _offset_to_latlon(lat_a: float, lon_a: float, x_m: float, y_m: float) -> dict:
    lat_rad = lat_a * math.pi / 180
    meters_per_deg_lon = METERS_PER_DEG_LAT * math.cos(lat_rad)
    return {
        "latitude": lat_a + (y_m / METERS_PER_DEG_LAT),
        "longitude": lon_a + (x_m / meters_per_deg_lon),
    }


def generate_viewports(lat_a: float, lon_a: float, square_size: float) -> list[dict]:
    """
    Generate 36 viewport rectangles using the MAD MAX grid algorithm.
    square_size is in meters (e.g. 2000 = 2km grid spacing).
    """
    a = square_size

    # 25 named grid points (A–Y) — offsets in meters from center
    pts = {
        "A": [0, 0],
        "B": [a, a],   "C": [a, -a],   "D": [-a, a],   "E": [-a, -a],
        "F": [2*a, 0],  "G": [2*a, 2*a], "H": [0, 2*a],  "I": [-2*a, 2*a],
        "J": [-2*a, 0], "K": [-2*a, -2*a], "L": [0, -2*a], "M": [2*a, -2*a],
        "N": [3*a, a],  "O": [3*a, 3*a],  "P": [a, 3*a],  "Q": [-a, 3*a],
        "R": [-3*a, 3*a], "S": [-3*a, a],  "T": [-3*a, -a], "U": [-3*a, -3*a],
        "V": [-a, -3*a], "W": [a, -3*a],  "X": [3*a, -3*a], "Y": [3*a, -a],
    }

    # Convert all points to lat/lon
    geo = {name: _offset_to_latlon(lat_a, lon_a, x, y) for name, (x, y) in pts.items()}

    # 36 diagonal viewport pairs
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
                "latitude": min(p1["latitude"], p2["latitude"]),
                "longitude": min(p1["longitude"], p2["longitude"]),
            },
            "high": {
                "latitude": max(p1["latitude"], p2["latitude"]),
                "longitude": max(p1["longitude"], p2["longitude"]),
            },
        })

    return viewports


# ── New Places API search per viewport ────────────────────────────────

async def _search_viewport(
    client: httpx.AsyncClient,
    keyword: str,
    viewport: dict,
    api_key: str,
) -> list[dict]:
    """Single viewport search using the new Places API."""
    payload = {
        "textQuery": keyword,
        "locationRestriction": {"rectangle": viewport},
        "maxResultCount": 20,
    }
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": NEW_API_FIELD_MASK,
        "Content-Type": "application/json",
    }

    try:
        resp = await client.post(PLACES_NEW_SEARCH_URL, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []  # best-effort — skip failed viewports

    results = []
    for place in data.get("places", []):
        website = place.get("websiteUri")
        place_id = place.get("id", "")
        name = place.get("displayName", {}).get("text", "")
        types = place.get("types", [])
        results.append({
            "google_place_id": place_id,
            "business_name": name,
            "address": place.get("formattedAddress"),
            "phone": place.get("nationalPhoneNumber"),
            "website": website,
            "domain": _extract_domain(website),
            "category": ", ".join(types[:3]),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "maps_url": place.get("googleMapsUri") or f"https://maps.google.com/?q={name}",
        })
    return results


def generate_outer_centers(lat_a: float, lon_a: float, square_size: float) -> list[dict]:
    """
    Outer ring generator — second n8n node.
    Places 5 sweep centers around the origin at spacing = 3*2*square_size meters.
    Combined with the origin that gives 6 total sweep centers that tile seamlessly.

    Points (commented-out ones from original are excluded):
      Top-middle, Top-left, Middle-left, Bottom-left, Bottom-middle
    """
    a = 3 * 2 * square_size  # = 6 × square_size

    offsets = [
        (0,  a),   # Top-middle
        (-a, a),   # Top-left
        (-a, 0),   # Middle-left
        (-a, -a),  # Bottom-left
        (0,  -a),  # Bottom-middle
    ]

    return [_offset_to_latlon(lat_a, lon_a, x, y) for x, y in offsets]


async def grid_search_businesses(
    keyword: str,
    location: str,
    api_key: str,
    square_size: float = 2000,
    progress_callback=None,
) -> list[dict]:
    """
    Single-center grid scrape — 36 viewports, up to 720 results.
    progress_callback(done, total, found) called after each viewport.
    """
    lat, lon = await geocode_location(location, api_key)
    viewports = generate_viewports(lat, lon, square_size)

    seen_ids = set()
    all_results = []
    total = len(viewports)

    async with httpx.AsyncClient() as client:
        for i, viewport in enumerate(viewports):
            batch = await _search_viewport(client, keyword, viewport, api_key)
            for biz in batch:
                pid = biz.get("google_place_id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_results.append(biz)

            if progress_callback:
                await progress_callback(i + 1, total, len(all_results))

    return all_results


async def deep_search_businesses(
    keyword: str,
    location: str,
    api_key: str,
    square_size: float = 2000,
    progress_callback=None,
) -> list[dict]:
    """
    Deep Sweep — 6 sweep centers × 36 viewports = 216 total viewport calls.
    Up to 4,320 raw results before deduplication.

    Centers: 1 origin + 5 outer ring points at 6× square_size spacing.
    The outer spacing ensures grids tile with no gaps and minimal overlap.

    progress_callback(done, total, found) called after each viewport across all centers.
    """
    lat, lon = await geocode_location(location, api_key)

    # All 6 sweep centers: origin + 5 outer ring
    outer = generate_outer_centers(lat, lon, square_size)
    centers = [{"latitude": lat, "longitude": lon}] + outer

    # Build all viewports across all 6 centers
    all_viewports = []
    for center in centers:
        vps = generate_viewports(center["latitude"], center["longitude"], square_size)
        all_viewports.extend(vps)

    seen_ids = set()
    all_results = []
    total = len(all_viewports)  # 216

    async with httpx.AsyncClient() as client:
        for i, viewport in enumerate(all_viewports):
            batch = await _search_viewport(client, keyword, viewport, api_key)
            for biz in batch:
                pid = biz.get("google_place_id")
                if pid and pid not in seen_ids:
                    seen_ids.add(pid)
                    all_results.append(biz)

            if progress_callback:
                await progress_callback(i + 1, total, len(all_results))

    return all_results


# ── Original quick search (kept for Quick Search mode) ────────────────

async def search_businesses(keyword: str, location: str, api_key: str, max_results: int = 60) -> list[dict]:
    """Quick search — single text query, up to 60 results."""
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
                results.append({
                    "google_place_id": place.get("place_id"),
                    "business_name": place.get("name"),
                    "address": place.get("formatted_address"),
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

    place_ids = [r["google_place_id"] for r in results if r.get("google_place_id")]
    details_map = await _batch_place_details(place_ids, api_key)

    for result in results:
        pid = result.get("google_place_id")
        if pid and pid in details_map:
            detail = details_map[pid]
            website = detail.get("website")
            result["website"] = website
            result["phone"] = detail.get("formatted_phone_number")
            result["domain"] = _extract_domain(website)

    return results


async def _batch_place_details(place_ids: list[str], api_key: str, client_timeout: int = 30) -> dict:
    details_map = {}
    fields = "website,formatted_phone_number"
    async with httpx.AsyncClient(timeout=client_timeout) as client:
        for pid in place_ids:
            try:
                resp = await client.get(PLACES_DETAILS_URL, params={"place_id": pid, "fields": fields, "key": api_key})
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "OK":
                    details_map[pid] = data.get("result", {})
            except Exception:
                pass
    return details_map

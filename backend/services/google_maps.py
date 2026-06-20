import httpx
from typing import Optional
from urllib.parse import urlparse


PLACES_TEXT_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
PLACES_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


def _extract_domain(website: Optional[str]) -> Optional[str]:
    if not website:
        return None
    try:
        parsed = urlparse(website if website.startswith("http") else f"https://{website}")
        domain = parsed.netloc.replace("www.", "")
        return domain if domain else None
    except Exception:
        return None


async def search_businesses(keyword: str, location: str, api_key: str, max_results: int = 60) -> list[dict]:
    """Search Google Maps Places API. Returns up to max_results businesses."""
    results = []
    next_page_token = None

    async with httpx.AsyncClient(timeout=30) as client:
        while len(results) < max_results:
            params = {
                "query": f"{keyword} in {location}",
                "key": api_key,
            }
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

    # Enrich with website + phone from Place Details for each result
    place_ids = [r["google_place_id"] for r in results if r.get("google_place_id")]
    details_map = await _batch_place_details(place_ids, api_key, client_timeout=30)

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
                resp = await client.get(PLACES_DETAILS_URL, params={
                    "place_id": pid,
                    "fields": fields,
                    "key": api_key,
                })
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "OK":
                    details_map[pid] = data.get("result", {})
            except Exception:
                pass  # best-effort enrichment

    return details_map

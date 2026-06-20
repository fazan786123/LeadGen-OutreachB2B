"""
Unified email finder chain — tries all tiers in order, stops at first hit.

Priority:
  1. Website scraper          (free, unlimited)
  2. Pattern guesser + SMTP   (free, unlimited)
  3. Apollo.io                (50 free/month, best quality)
  4. Snov.io                  (50 free/month, good global)
  5. Skrapp.io                (100 free/month)
  6. Findthat.email           (50 free/month)
  7. Hunter.io                (25 free/month — fewest credits, used last)

Each tier is skipped silently if its API key is not configured.
"""

from config import get_settings
from services.website_scraper import scrape_website_email
from services.pattern_guesser import guess_email_for_domain
from services.email_finder import apollo_find, snov_find, skrapp_find, findthat_find, hunter_find


def _should_retry_on_credits(result: dict) -> bool:
    """Try the next API key/account when credits or rate limits are exhausted."""
    if result["status"] != "error":
        return False
    err = str(result.get("error", "")).lower()
    return any(x in err for x in ("credit", "limit", "429", "quota", "exhausted"))


async def find_email_chain(domain: str, website: str = "") -> dict:
    """
    Run the full email finder chain for a domain.
    Returns the first successful result with the source that found it.

    Result shape:
      { status: "found"|"not_found", email, name, title, confidence, source, tried }
    """
    settings = get_settings()
    tried: list[str] = []

    # ── Tier 1a: Website scraper ──────────────────────────────────────
    if website or domain:
        tried.append("website_scrape")
        result = await scrape_website_email(website or f"https://{domain}", domain)
        if result["status"] == "found":
            return {**result, "tried": tried}

    # ── Tier 1b: Pattern guesser + SMTP verify ────────────────────────
    tried.append("pattern_guess")
    result = await guess_email_for_domain(domain)
    if result["status"] == "found":
        return {**result, "tried": tried}

    # ── Tier 2: API providers (skip if no key configured) ─────────────

    # Apollo.io — rotates keys if credits run out
    apollo_keys = settings.apollo_api_keys
    if apollo_keys:
        tried.append("apollo")
        for key in apollo_keys:
            result = await apollo_find(domain, key)
            if result["status"] == "found":
                return {**result, "tried": tried}
            if result["status"] == "not_found":
                break
            if not _should_retry_on_credits(result):
                break

    # Snov.io — rotates accounts if credits run out
    snov_accounts = settings.snov_credentials
    if snov_accounts:
        tried.append("snov")
        for client_id, client_secret in snov_accounts:
            result = await snov_find(domain, client_id, client_secret)
            if result["status"] == "found":
                return {**result, "tried": tried}
            if result["status"] == "not_found":
                break
            if not _should_retry_on_credits(result):
                break

    # Skrapp.io
    if settings.skrapp_api_key:
        tried.append("skrapp")
        result = await skrapp_find(domain, settings.skrapp_api_key)
        if result["status"] == "found":
            return {**result, "tried": tried}

    # Findthat.email
    if settings.findthat_api_key:
        tried.append("findthat")
        result = await findthat_find(domain, settings.findthat_api_key)
        if result["status"] == "found":
            return {**result, "tried": tried}

    # Hunter.io — last resort (fewest free credits); rotates keys if credits run out
    hunter_keys = settings.hunter_api_keys
    if hunter_keys:
        tried.append("hunter")
        for key in hunter_keys:
            result = await hunter_find(domain, key)
            if result["status"] == "found":
                return {**result, "tried": tried}
            if result["status"] == "not_found":
                break
            if not _should_retry_on_credits(result):
                break

    return {"status": "not_found", "source": None, "tried": tried}

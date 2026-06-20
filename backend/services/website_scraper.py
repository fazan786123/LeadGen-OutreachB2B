"""
Tier 1a — Website email scraper (free, unlimited)

Fetches the business website and extracts emails from:
  1. mailto: links (most reliable)
  2. Regex pattern matches in page text
  3. Contact page (/contact, /about, /team) if homepage has nothing

Scores emails to pick the best decision-maker contact:
  - Deprioritises generic addresses (info@, contact@, etc.)
  - Prefers named addresses (john@, jsmith@, etc.)
"""

import re
import httpx
from urllib.parse import urljoin, urlparse

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')

GENERIC_PREFIXES = {
    "info", "contact", "hello", "enquiries", "enquiry", "support",
    "admin", "office", "mail", "team", "general", "help", "sales",
    "noreply", "no-reply", "donotreply", "webmaster", "postmaster",
    "billing", "accounts", "reception", "bookings", "booking",
}

DECISION_MAKER_KEYWORDS = ["ceo", "founder", "owner", "director", "manager", "partner", "head", "vp", "md", "coo"]

CONTACT_PATHS = ["/contact", "/contact-us", "/about", "/about-us", "/team", "/our-team", "/reach-us", "/get-in-touch"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)",
    "Accept": "text/html,application/xhtml+xml",
}


def _score_email(email: str, page_text: str = "") -> int:
    prefix = email.split("@")[0].lower()
    if prefix in GENERIC_PREFIXES:
        return 1
    # Named email (contains a dot or looks like a person)
    if "." in prefix or any(k in prefix for k in DECISION_MAKER_KEYWORDS):
        return 10
    return 5


def _extract_emails(html: str) -> list[str]:
    # mailto: links first — most reliable
    mailto = re.findall(r'mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html, re.IGNORECASE)
    # regex sweep of visible text
    all_matches = EMAIL_REGEX.findall(html)
    # Combine, deduplicate, filter obvious junk
    seen = set()
    results = []
    for email in (mailto + all_matches):
        email = email.lower().strip(".,;:")
        domain = email.split("@")[-1]
        if email in seen:
            continue
        seen.add(email)
        # Filter image/asset filenames misidentified as emails
        if any(domain.endswith(ext) for ext in [".png", ".jpg", ".gif", ".svg", ".css", ".js"]):
            continue
        results.append(email)
    return results


async def _fetch_page(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, headers=HEADERS, timeout=10, follow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
            return resp.text
    except Exception:
        pass
    return ""


async def scrape_website_email(website: str, domain: str) -> dict:
    """
    Scrape a business website for the best decision-maker email.
    Checks homepage first, then common contact/about pages.
    """
    base_url = website if website.startswith("http") else f"https://{website}"
    # Normalise
    parsed = urlparse(base_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    all_emails: list[str] = []

    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Homepage
        html = await _fetch_page(client, base_url)
        if html:
            all_emails.extend(_extract_emails(html))

        # 2. Contact/about pages if homepage didn't give a named email
        has_named = any(_score_email(e) >= 5 for e in all_emails)
        if not has_named:
            for path in CONTACT_PATHS:
                html = await _fetch_page(client, urljoin(base_url, path))
                if html:
                    all_emails.extend(_extract_emails(html))
                if all_emails:
                    break  # stop after first contact page with results

    if not all_emails:
        return {"status": "not_found", "source": "website_scrape"}

    # Filter to emails on this domain only
    domain_emails = [e for e in all_emails if e.endswith(f"@{domain}") or domain in e.split("@")[-1]]
    candidates = domain_emails if domain_emails else all_emails

    # Pick best by score
    best = max(set(candidates), key=lambda e: _score_email(e))

    return {
        "status": "found",
        "email": best,
        "name": None,
        "title": None,
        "confidence": 70 if _score_email(best) >= 5 else 40,
        "source": "website_scrape",
    }

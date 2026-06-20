"""
Uses Hunter.io to find decision-maker emails for a given domain.
Free plan: 25 searches/month. Paid plans: 500–50,000/month.
Docs: https://hunter.io/api-documentation/v2
"""
import httpx

HUNTER_DOMAIN_SEARCH = "https://api.hunter.io/v2/domain-search"
HUNTER_EMAIL_FINDER = "https://api.hunter.io/v2/email-finder"


async def find_emails_for_domain(domain: str, api_key: str) -> dict:
    """
    Domain search — returns list of emails found for a domain.
    Picks the best candidate (highest confidence, seniority = executive/director/manager first).
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(HUNTER_DOMAIN_SEARCH, params={
            "domain": domain,
            "api_key": api_key,
            "limit": 10,
        })
        resp.raise_for_status()
        data = resp.json()

    if data.get("errors"):
        return {"status": "error", "error": str(data["errors"])}

    emails = data.get("data", {}).get("emails", [])
    if not emails:
        return {"status": "not_found"}

    priority_titles = ["ceo", "founder", "owner", "president", "director", "manager", "head", "vp", "partner"]

    def score(e):
        title = (e.get("position") or "").lower()
        title_score = next((10 - i for i, t in enumerate(priority_titles) if t in title), 0)
        return (e.get("confidence") or 0) + title_score * 5

    best = max(emails, key=score)
    return {
        "status": "found",
        "email": best.get("value"),
        "name": f"{best.get('first_name', '')} {best.get('last_name', '')}".strip() or None,
        "title": best.get("position"),
        "confidence": best.get("confidence"),
    }


async def find_email_by_name(first_name: str, last_name: str, domain: str, api_key: str) -> dict:
    """Email Finder — when you already know the person's name."""
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.get(HUNTER_EMAIL_FINDER, params={
            "domain": domain,
            "first_name": first_name,
            "last_name": last_name,
            "api_key": api_key,
        })
        resp.raise_for_status()
        data = resp.json()

    if data.get("errors"):
        return {"status": "error", "error": str(data["errors"])}

    email_data = data.get("data", {})
    if not email_data.get("email"):
        return {"status": "not_found"}

    return {
        "status": "found",
        "email": email_data["email"],
        "name": f"{first_name} {last_name}".strip(),
        "confidence": email_data.get("score"),
    }

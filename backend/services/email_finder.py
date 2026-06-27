"""
Tier 2 — API-based email finders (free tiers)

Provider        Free credits/month    Quality
─────────────────────────────────────────────
Apollo.io       50                    Best (US focus, strong B2B)
Snov.io         50                    Good (global, strong EU)
Skrapp.io       100                   Decent (weakest data, most credits)
Findthat.email  50                    Decent
Hunter.io       25                    Good (use last — fewest credits)

Each provider returns a normalised dict:
  { status, email, name, title, confidence, source }
"""

import httpx
from typing import Optional

PRIORITY_TITLES = ["ceo", "founder", "owner", "president", "director", "manager", "head", "vp", "partner", "md"]


def _title_score(title: Optional[str]) -> int:
    if not title:
        return 0
    t = title.lower()
    return next((len(PRIORITY_TITLES) - i for i, kw in enumerate(PRIORITY_TITLES) if kw in t), 0)


def _best_email(emails: list[dict]) -> dict:
    """Pick the highest-value contact from a list of email dicts."""
    if not emails:
        return {}
    return max(emails, key=lambda e: (e.get("confidence") or 0) + _title_score(e.get("title")) * 5)


# ── Apollo.io ─────────────────────────────────────────────────────────

async def apollo_find(domain: str, api_key: str) -> dict:
    """
    Apollo People Search by domain.
    Docs: https://apolloio.github.io/apollo-api-docs/
    Free: 50 credits/month
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.apollo.io/v1/mixed_people/search",
                json={
                    "api_key": api_key,
                    "q_organization_domains": domain,
                    "page": 1,
                    "per_page": 10,
                    "person_titles": ["CEO", "Founder", "Owner", "Director", "Manager", "Partner", "President"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"status": "error", "source": "apollo", "error": str(e)}

    people = data.get("people", [])
    candidates = []
    for p in people:
        email = p.get("email")
        if not email or "apollo" in email:
            continue
        candidates.append({
            "email": email,
            "name": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "title": p.get("title"),
            "confidence": 85,
        })

    if not candidates:
        return {"status": "not_found", "source": "apollo"}

    best = _best_email(candidates)
    return {"status": "found", "source": "apollo", **best}


# ── Snov.io ───────────────────────────────────────────────────────────

async def snov_find(domain: str, client_id: str, client_secret: str) -> dict:
    """
    Snov.io Domain Search.
    Docs: https://snov.io/api
    Free: 50 credits/month
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # Get access token
            token_resp = await client.post(
                "https://api.snov.io/v1/oauth/access_token",
                json={"grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret},
            )
            token_resp.raise_for_status()
            token = token_resp.json().get("access_token")
            if not token:
                return {"status": "error", "source": "snov", "error": "no token"}

            resp = await client.post(
                "https://api.snov.io/v2/domain-emails-with-info",
                json={"domain": domain, "type": "all", "limit": 10},
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"status": "error", "source": "snov", "error": str(e)}

    emails = data.get("emails", [])
    candidates = []
    for e in emails:
        email_addr = e.get("email")
        if not email_addr:
            continue
        first = e.get("firstName", "")
        last = e.get("lastName", "")
        candidates.append({
            "email": email_addr,
            "name": f"{first} {last}".strip() or None,
            "title": e.get("position"),
            "confidence": e.get("confidence", 70),
        })

    if not candidates:
        return {"status": "not_found", "source": "snov"}

    best = _best_email(candidates)
    return {"status": "found", "source": "snov", **best}


# ── Skrapp.io ─────────────────────────────────────────────────────────

async def skrapp_find(domain: str, api_key: str) -> dict:
    """
    Skrapp.io Domain Search.
    Docs: https://skrapp.io/api
    Free: 100 credits/month
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.skrapp.io/api/v2/emails",
                params={"domain": domain, "limit": 10},
                headers={"X-Access-Key": api_key, "Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"status": "error", "source": "skrapp", "error": str(e)}

    emails = data.get("emails", [])
    candidates = []
    for e in emails:
        email_addr = e.get("email")
        if not email_addr:
            continue
        candidates.append({
            "email": email_addr,
            "name": f"{e.get('firstName', '')} {e.get('lastName', '')}".strip() or None,
            "title": e.get("position"),
            "confidence": e.get("accuracy", 60),
        })

    if not candidates:
        return {"status": "not_found", "source": "skrapp"}

    best = _best_email(candidates)
    return {"status": "found", "source": "skrapp", **best}


# ── Findthat.email ────────────────────────────────────────────────────

async def findthat_find(domain: str, api_key: str) -> dict:
    """
    Findthat.email Domain Search.
    Docs: https://findthat.email/api/docs
    Free: 50 credits/month
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.findthat.email/v1/search",
                params={"domain": domain},
                headers={"X-Api-Key": api_key},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"status": "error", "source": "findthat", "error": str(e)}

    emails = data.get("emails", [])
    candidates = []
    for e in emails:
        email_addr = e.get("value")
        if not email_addr:
            continue
        candidates.append({
            "email": email_addr,
            "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip() or None,
            "title": e.get("position"),
            "confidence": e.get("confidence", 60),
        })

    if not candidates:
        return {"status": "not_found", "source": "findthat"}

    best = _best_email(candidates)
    return {"status": "found", "source": "findthat", **best}


# ── Hunter.io ─────────────────────────────────────────────────────────

async def hunter_has_emails(domain: str, api_key: str) -> bool:
    """
    Free preflight check — asks Hunter how many emails they have for a domain.
    Uses limit=0 so no credit is consumed. Returns True only if count > 0.
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": api_key, "limit": 0},
            )
            if not resp.is_success:
                return True  # unknown — allow the real call to decide
            data = resp.json()
        return (data.get("data", {}).get("meta", {}).get("results", 0) or 0) > 0
    except Exception:
        return True  # network error — allow the real call to decide


async def hunter_find(domain: str, api_key: str) -> dict:
    """
    Hunter.io Domain Search.
    Docs: https://hunter.io/api-documentation/v2
    Free: 25 credits/month — use last
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "api_key": api_key, "limit": 10},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        return {"status": "error", "source": "hunter", "error": str(e)}

    if data.get("errors"):
        return {"status": "error", "source": "hunter", "error": str(data["errors"])}

    emails = data.get("data", {}).get("emails", [])
    candidates = []
    for e in emails:
        email_addr = e.get("value")
        if not email_addr:
            continue
        candidates.append({
            "email": email_addr,
            "name": f"{e.get('first_name', '')} {e.get('last_name', '')}".strip() or None,
            "title": e.get("position"),
            "confidence": e.get("confidence", 70),
        })

    if not candidates:
        return {"status": "not_found", "source": "hunter"}

    best = _best_email(candidates)
    return {"status": "found", "source": "hunter", **best}

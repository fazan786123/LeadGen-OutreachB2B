"""
Tier 0 — Decision-maker finder via Brave Search API (2,000 free queries/month)

Strategy:
  1. LinkedIn search  — "{business_name}" site:linkedin.com/in
     Snippets follow the pattern "First Last - Title at Company · LinkedIn"
  2. General search   — "{business_name}" "{location}" owner OR CEO OR founder
     Extracts names/titles from result snippets using heuristics

Uses 1-2 queries per lead. Results cached in DB so each lead is only queried once.
"""

import re
import httpx
from typing import Optional

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Titles we consider decision-makers, in priority order
DM_TITLES = [
    "founder", "co-founder", "cofounder",
    "owner", "co-owner",
    "ceo", "chief executive",
    "president", "managing director", "md",
    "director", "principal",
    "partner", "managing partner",
    "head", "vp", "vice president",
    "manager", "general manager",
]

# LinkedIn snippet: "First Last - Title at Company · LinkedIn"
_LINKEDIN_RE = re.compile(
    r'^([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s[-–]\s([^·\n]{3,60}?)(?:\s(?:at|@)\s[^·\n]+)?\s[·|]',
    re.MULTILINE,
)

# General snippet patterns like "John Smith, CEO of Acme" / "CEO John Smith"
_NAME_TITLE_RE = re.compile(
    r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)+),?\s+(' + '|'.join(DM_TITLES) + r')',
    re.IGNORECASE,
)
_TITLE_NAME_RE = re.compile(
    r'\b(' + '|'.join(DM_TITLES) + r')[,:]?\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)',
    re.IGNORECASE,
)


def _title_priority(title: str) -> int:
    t = title.lower()
    for i, kw in enumerate(DM_TITLES):
        if kw in t:
            return i
    return 99


def _extract_from_snippets(snippets: list[str], linkedin: bool = False) -> Optional[dict]:
    best = None
    best_priority = 99

    for snippet in snippets:
        if linkedin:
            m = _LINKEDIN_RE.search(snippet)
            if m:
                name, title = m.group(1).strip(), m.group(2).strip()
                p = _title_priority(title)
                if p < best_priority:
                    best_priority = p
                    best = {"name": name, "title": title}
            continue

        for pattern, name_grp, title_grp in [
            (_NAME_TITLE_RE, 1, 2),
            (_TITLE_NAME_RE, 2, 1),
        ]:
            for m in pattern.finditer(snippet):
                name = m.group(name_grp).strip()
                title = m.group(title_grp).strip()
                p = _title_priority(title)
                if p < best_priority:
                    best_priority = p
                    best = {"name": name, "title": title}

    return best


async def _brave_search(query: str, api_key: str, count: int = 5) -> list[str]:
    """Returns list of snippet strings from Brave Search results."""
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": count, "search_lang": "en", "result_filter": "web"}

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(BRAVE_SEARCH_URL, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()

    snippets = []
    for result in data.get("web", {}).get("results", []):
        title = result.get("title", "")
        desc = result.get("description", "")
        if title:
            snippets.append(title)
        if desc:
            snippets.append(desc)

    return snippets


async def find_decision_maker(
    business_name: str,
    location: str = "",
    domain: str = "",
    api_key: str = "",
) -> dict:
    """
    Search Brave for the decision-maker of a business.

    Returns:
      { status: "found"|"not_found", name, title, source: "brave_linkedin"|"brave_search" }
    """
    if not api_key:
        return {"status": "not_found", "name": None, "title": None, "source": None}

    # ── Query 1: LinkedIn ─────────────────────────────────────────────────
    li_query = f'"{business_name}" site:linkedin.com/in'
    try:
        snippets = await _brave_search(li_query, api_key, count=5)
        result = _extract_from_snippets(snippets, linkedin=True)
        if result:
            return {**result, "status": "found", "source": "brave_linkedin"}
    except Exception:
        pass  # fall through to general search

    # ── Query 2: General web ──────────────────────────────────────────────
    loc_part = f' "{location}"' if location else ""
    gen_query = f'"{business_name}"{loc_part} owner OR CEO OR founder OR director'
    try:
        snippets = await _brave_search(gen_query, api_key, count=5)
        result = _extract_from_snippets(snippets, linkedin=False)
        if result:
            return {**result, "status": "found", "source": "brave_search"}
    except Exception:
        pass

    return {"status": "not_found", "name": None, "title": None, "source": None}

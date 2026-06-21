"""
Tier 0 — Decision-maker finder via Brave Search API (2,000 free queries/month)

Strategy:
  1. LinkedIn search  — "{business_name}" site:linkedin.com/in
     Snippets follow the pattern "First Last - Title at Company · LinkedIn"
  2. General search   — "{business_name}" "{location}" owner OR CEO OR founder
     Extracts names/titles from result snippets using heuristics

Uses 1-2 queries per lead. Results cached in DB so each lead is only queried once.
Returns up to max_contacts (default 5) ranked by title priority.
"""

import re
import httpx
from typing import Optional
from services.team_scraper import scrape_team_page

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Titles we consider decision-makers, in priority order
DM_TITLES = [
    "founder", "co-founder", "cofounder",
    "owner", "co-owner",
    "ceo", "chief executive", "cto", "coo", "cfo",
    "president", "managing director", "md",
    "director", "principal",
    "partner", "managing partner",
    "head", "vp", "vice president",
    "manager", "general manager",
    "consultant", "advisor", "adviser",
    "proprietor", "operator", "specialist",
]

# LinkedIn snippet: "First Last - Title at Company · LinkedIn"
# No ^ anchor — match anywhere in the snippet
_LINKEDIN_RE = re.compile(
    r'([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\s[-–]\s([^·\n]{3,60}?)(?:\s(?:at|@)\s[^·\n]+)?\s[·|]',
    re.MULTILINE,
)

# Case-sensitive name pattern — [A-Z] only matches uppercase (no IGNORECASE flag)
_NAME_PAT = r'([A-Z][a-z]{1,20}(?:\s[A-Z][a-z]{1,20}){1,3})'

# Title pattern — case-insensitive via inline flag
_TITLE_PAT = r'(?i:' + '|'.join(re.escape(t) for t in DM_TITLES) + r')'

# "CEO John Smith" / "Director Jane Doe"
_TITLE_NAME_RE = re.compile(r'\b' + _TITLE_PAT + r'[,:]?\s+' + _NAME_PAT)

# "John Smith, CEO" / "Jane Doe - Director"
_NAME_TITLE_RE = re.compile(_NAME_PAT + r'[,\s\-]+' + _TITLE_PAT + r'\b')

# Words that are NOT person names even if capitalised
_NOT_A_NAME = {
    # Places / map words
    "london", "manchester", "birmingham", "leeds", "bristol", "glasgow",
    "edinburgh", "liverpool", "sheffield", "nottingham", "cardiff",
    "maps", "street", "road", "avenue", "lane", "drive", "close",
    # Search engines / brands
    "google", "bing", "yahoo", "facebook", "linkedin", "twitter",
    # Generic business words
    "services", "solutions", "limited", "company", "group", "associates",
    "partners", "practice", "clinic", "centre", "center", "dental", "medical",
    "health", "care", "professional", "business", "enterprise", "enterprises",
    "international", "national", "global", "local",
    # Sector words
    "surgery", "hospital", "academy", "school", "college", "university",
    "institute", "trust", "foundation", "charity",
    # Common false-positive words
    "the", "and", "for", "with", "our", "all", "more", "including",
    "contact", "about", "home", "new", "view", "get", "find",
    "meet", "team", "staff", "management", "financials",
}


def _is_valid_name(name: str) -> bool:
    """Return True only if the name looks like a real person."""
    words = name.strip().split()
    if len(words) < 2 or len(words) > 4:
        return False
    for w in words:
        if w.lower() in _NOT_A_NAME:
            return False
        if len(w) < 2:
            return False
        if not w[0].isupper():
            return False
        # Reject all-caps abbreviations like "NHS", "CEO" captured as name
        if w.isupper() and len(w) > 2:
            return False
    return True


def _title_priority(title: str) -> int:
    t = title.lower()
    for i, kw in enumerate(DM_TITLES):
        if kw in t:
            return i
    return 99


def _extract_from_snippets(snippets: list[str], linkedin: bool = False, max_contacts: int = 5) -> list[dict]:
    """Return up to max_contacts unique contacts ranked by title priority."""
    seen_names: set[str] = set()
    candidates: list[tuple[int, dict]] = []  # (priority, contact)

    for snippet in snippets:
        if linkedin:
            m = _LINKEDIN_RE.search(snippet)
            if m:
                name, title = m.group(1).strip(), m.group(2).strip()
                if _is_valid_name(name) and name not in seen_names:
                    seen_names.add(name)
                    candidates.append((_title_priority(title), {"name": name, "title": title}))
            continue

        for pattern, name_grp, title_grp in [
            (_NAME_TITLE_RE, 1, 2),
            (_TITLE_NAME_RE, 2, 1),
        ]:
            for m in pattern.finditer(snippet):
                name = m.group(name_grp).strip()
                title = m.group(title_grp).strip()
                if not _is_valid_name(name):
                    continue
                if name in seen_names:
                    continue
                seen_names.add(name)
                candidates.append((_title_priority(title), {"name": name, "title": title}))

    candidates.sort(key=lambda x: x[0])
    return [c for _, c in candidates[:max_contacts]]


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


async def find_decision_makers(
    business_name: str,
    location: str = "",
    domain: str = "",
    api_key: str = "",
    max_contacts: int = 5,
) -> dict:
    all_contacts: list[dict] = []
    existing_names: set[str] = set()
    debug: list[str] = []

    def _merge(new_contacts: list[dict]):
        for c in new_contacts:
            if c["name"] not in existing_names:
                existing_names.add(c["name"])
                all_contacts.append(c)

    # ── Source 1: Website team page ───────────────────────────────────────
    if domain:
        try:
            contacts = await scrape_team_page(domain, max_contacts=max_contacts)
            debug.append(f"team_page: {len(contacts)} contacts")
            _merge(contacts)
        except Exception as e:
            debug.append(f"team_page error: {e}")

    # ── Source 2: LinkedIn via Brave ──────────────────────────────────────
    if api_key and len(all_contacts) < max_contacts:
        li_query = f'"{business_name}" site:linkedin.com/in'
        try:
            snippets = await _brave_search(li_query, api_key, count=10)
            contacts = _extract_from_snippets(snippets, linkedin=True, max_contacts=max_contacts)
            debug.append(f"linkedin: {len(snippets)} snippets → {len(contacts)} contacts")
            for c in contacts:
                c["source"] = "brave_linkedin"
            _merge(contacts)
        except Exception as e:
            debug.append(f"linkedin error: {e}")

    # ── Source 3: General web via Brave ───────────────────────────────────
    if api_key and len(all_contacts) < max_contacts:
        loc_part = f' "{location}"' if location else ""
        gen_query = (
            f'"{business_name}"{loc_part} '
            f'owner OR CEO OR founder OR director OR manager OR '
            f'principal OR proprietor OR partner OR "managing director"'
        )
        try:
            snippets = await _brave_search(gen_query, api_key, count=10)
            contacts = _extract_from_snippets(snippets, linkedin=False, max_contacts=max_contacts)
            debug.append(f"web_search: {len(snippets)} snippets → {len(contacts)} contacts")
            for c in contacts:
                c["source"] = "brave_search"
            _merge(contacts)
        except Exception as e:
            debug.append(f"web_search error: {e}")

    if all_contacts:
        result = all_contacts[:max_contacts]
        return {"status": "found", "contacts": result, "source": result[0]["source"], "debug": debug}

    return {"status": "not_found", "contacts": [], "source": None, "debug": debug}


# Backwards-compatible single-result wrapper
async def find_decision_maker(
    business_name: str,
    location: str = "",
    domain: str = "",
    api_key: str = "",
) -> dict:
    result = await find_decision_makers(business_name, location, domain, api_key, max_contacts=1)
    if result["status"] == "found" and result["contacts"]:
        c = result["contacts"][0]
        return {"status": "found", "name": c["name"], "title": c["title"], "source": c["source"]}
    return {"status": "not_found", "name": None, "title": None, "source": None}

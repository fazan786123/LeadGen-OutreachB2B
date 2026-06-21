"""
Team page scraper — finds decision-makers from a business's own website.

Strategy:
  1. Try common team/about page paths on the domain
  2. Parse HTML for person cards using structural heuristics:
     - Schema.org Person markup (<div itemtype="Person">)
     - Common CSS class names (.team, .staff, .person, .member, .bio etc.)
     - Heading + sibling/child paragraph patterns (h3 Name → p Title)
  3. Validate names against the same blocklist as people_finder
  4. Return up to max_contacts ranked by title priority

Cost: zero — just HTTP requests to the business's own website.
Failure modes: Cloudflare JS challenges, React SPAs, timeouts → returns []
"""

import re
import httpx
from bs4 import BeautifulSoup, Tag
from typing import Optional

# Paths to try in order — most common first
TEAM_PATHS = [
    "/team",
    "/our-team",
    "/meet-the-team",
    "/about",
    "/about-us",
    "/staff",
    "/people",
    "/who-we-are",
    "/meet-us",
    "/the-team",
    "/our-people",
    "/partners",
    "/directors",
    "/management",
    "/leadership",
]

# CSS class / id fragments that suggest a team section
_TEAM_HINTS = re.compile(
    r'team|staff|member|person|bio|people|about|profile|employee|director|partner',
    re.IGNORECASE,
)

# Title keywords for scoring
DM_TITLES = [
    "founder", "co-founder", "cofounder",
    "owner", "co-owner",
    "ceo", "chief executive",
    "president", "managing director", "md",
    "director", "principal",
    "partner", "managing partner",
    "head", "vp", "vice president",
    "manager", "general manager",
    "doctor", "dr", "gp", "general practitioner",
    "solicitor", "barrister", "consultant",
    "accountant", "architect", "engineer",
    "dentist", "optometrist", "physiotherapist",
]

_NOT_A_NAME = {
    "london", "manchester", "birmingham", "leeds", "bristol", "glasgow",
    "edinburgh", "liverpool", "sheffield", "nottingham", "cardiff",
    "maps", "street", "road", "avenue", "lane", "drive", "close",
    "google", "bing", "yahoo", "facebook", "linkedin", "twitter",
    "services", "solutions", "limited", "company", "group", "associates",
    "partners", "practice", "clinic", "centre", "center", "dental", "medical",
    "health", "care", "professional", "business", "enterprise", "enterprises",
    "international", "national", "global", "local",
    "surgery", "hospital", "academy", "school", "college", "university",
    "institute", "trust", "foundation", "charity",
    "the", "and", "for", "with", "our", "all", "more", "including",
    "contact", "about", "home", "new", "view", "get", "find",
    "meet", "team", "staff", "management", "financials", "read", "more",
    "click", "here", "learn", "see", "show", "hide", "menu",
}

_PROPER_NAME_RE = re.compile(r'^[A-Z][a-z]{1,25}(?:\s[A-Z][a-z]{1,25}){1,3}$')


def _is_valid_name(text: str) -> bool:
    text = text.strip()
    if not _PROPER_NAME_RE.match(text):
        return False
    for w in text.split():
        if w.lower() in _NOT_A_NAME:
            return False
        if len(w) < 2:
            return False
        if w.isupper() and len(w) > 2:
            return False
    return True


def _title_priority(title: str) -> int:
    t = title.lower()
    for i, kw in enumerate(DM_TITLES):
        if kw in t:
            return i
    return 99


def _is_title_like(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    t = text.lower()
    return any(kw in t for kw in DM_TITLES)


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _extract_from_soup(soup: BeautifulSoup) -> list[dict]:
    """
    Extract person cards from parsed HTML. Returns list of {name, title}.
    """
    contacts: list[dict] = []
    seen: set[str] = set()

    def add(name: str, title: str):
        name = _clean(name)
        title = _clean(title)
        if _is_valid_name(name) and name not in seen and _is_title_like(title):
            seen.add(name)
            contacts.append({"name": name, "title": title})

    # ── Strategy 1: Schema.org Person markup ─────────────────────────────
    for el in soup.find_all(attrs={"itemtype": re.compile(r'Person', re.I)}):
        name_el = el.find(attrs={"itemprop": "name"})
        job_el = el.find(attrs={"itemprop": re.compile(r'jobTitle|title', re.I)})
        if name_el and job_el:
            add(name_el.get_text(), job_el.get_text())

    # ── Strategy 2: Team-hinted containers ───────────────────────────────
    # Find divs/sections/articles whose class or id suggests a team/person card
    for el in soup.find_all(['div', 'article', 'section', 'li']):
        classes = ' '.join(el.get('class', []))
        el_id = el.get('id', '')
        if not _TEAM_HINTS.search(classes + ' ' + el_id):
            continue

        # Look for a heading inside (name) + nearby paragraph (title)
        for heading_tag in ['h1', 'h2', 'h3', 'h4', 'h5']:
            for h in el.find_all(heading_tag):
                name_text = h.get_text()
                # Check siblings and children for title
                candidates = []
                # immediate next siblings
                for sib in h.next_siblings:
                    if isinstance(sib, Tag):
                        candidates.append(sib.get_text())
                        break
                # children of parent after heading
                for child in el.find_all(['p', 'span', 'small', 'div']):
                    t = child.get_text()
                    if _is_title_like(t) and len(t) < 100:
                        candidates.append(t)
                for candidate in candidates:
                    add(name_text, candidate)

    # ── Strategy 3: Heading immediately followed by title-like paragraph ─
    # Works for simple layouts: <h3>John Smith</h3><p>Director</p>
    for heading_tag in ['h2', 'h3', 'h4']:
        for h in soup.find_all(heading_tag):
            name_text = h.get_text()
            if not _is_valid_name(_clean(name_text)):
                continue
            # Check next sibling tags
            for sib in h.next_siblings:
                if not isinstance(sib, Tag):
                    continue
                sib_text = _clean(sib.get_text())
                if _is_title_like(sib_text) and len(sib_text) < 100:
                    add(name_text, sib_text)
                break  # only check the immediate next sibling

    # ── Strategy 4: "Dr John Smith" pattern in strong/b tags ─────────────
    dr_re = re.compile(
        r'\b((?:Dr|Mr|Mrs|Ms|Prof)\.?\s+[A-Z][a-z]{1,20}(?:\s[A-Z][a-z]{1,20}){0,3})',
    )
    for el in soup.find_all(['strong', 'b', 'p', 'span']):
        text = el.get_text()
        for m in dr_re.finditer(text):
            candidate = m.group(1).strip()
            # Remove the prefix for validation but keep it for display
            plain = re.sub(r'^(?:Dr|Mr|Mrs|Ms|Prof)\.?\s+', '', candidate)
            if _is_valid_name(plain):
                # Try to find a title nearby
                parent_text = _clean(el.parent.get_text()) if el.parent else ''
                title = ''
                for kw in DM_TITLES:
                    if kw in parent_text.lower():
                        # Extract sentence fragment containing the keyword
                        idx = parent_text.lower().find(kw)
                        title = parent_text[max(0, idx-10):idx+40].strip()
                        break
                if not title:
                    title = "General Practitioner" if "dr" in candidate.lower()[:3] else ""
                if title:
                    add(candidate, title)

    return contacts


async def _fetch_page(client: httpx.AsyncClient, url: str) -> Optional[BeautifulSoup]:
    """Fetch a URL and return parsed BeautifulSoup, or None on failure."""
    try:
        resp = await client.get(url, timeout=8, follow_redirects=True)
        if not resp.is_success:
            return None
        ct = resp.headers.get("content-type", "")
        if "html" not in ct and "text" not in ct:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


async def scrape_team_page(
    domain: str,
    website: str = "",
    max_contacts: int = 5,
) -> list[dict]:
    """
    Try common team/about paths on the domain and extract person contacts.
    Returns list of {name, title, source: "team_page"}.
    """
    if not domain:
        return []

    base = f"https://{domain}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    all_contacts: list[dict] = []
    seen_names: set[str] = set()

    async with httpx.AsyncClient(headers=headers) as client:
        for path in TEAM_PATHS:
            if len(all_contacts) >= max_contacts:
                break

            url = base + path
            soup = await _fetch_page(client, url)
            if not soup:
                continue

            page_contacts = _extract_from_soup(soup)
            for c in page_contacts:
                if c["name"] not in seen_names:
                    seen_names.add(c["name"])
                    c["source"] = "team_page"
                    all_contacts.append(c)

            # If we found contacts on this page, no need to try more paths
            if all_contacts:
                break

    # Sort by title priority
    all_contacts.sort(key=lambda c: _title_priority(c["title"]))
    return all_contacts[:max_contacts]

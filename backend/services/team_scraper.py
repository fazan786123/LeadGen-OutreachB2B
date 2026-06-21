"""
Team page scraper — finds decision-makers from a business's own website.

Strategy:
  1. Fetch homepage and extract any team/about links from nav/footer
  2. Try a broad list of common team/about page paths
  3. Parse each page with multiple strategies:
     a. Schema.org JSON-LD Person objects
     b. Schema.org microdata itemtype=Person
     c. Team-hinted CSS class containers
     d. Heading → sibling title pattern
     e. Dr./Mr./Mrs./Prof. prefix pattern
  4. Return up to max_contacts ranked by title priority
"""

import re
import json
import httpx
from bs4 import BeautifulSoup, Tag
from typing import Optional

TEAM_PATHS = [
    "/team",
    "/our-team",
    "/meet-the-team",
    "/meet-our-team",
    "/the-team",
    "/practice-team",
    "/staff",
    "/people",
    "/our-people",
    "/about",
    "/about-us",
    "/who-we-are",
    "/meet-us",
    "/partners",
    "/directors",
    "/management",
    "/leadership",
    "/executives",
    "/founders",
]

_TEAM_HINTS = re.compile(
    r'team|staff|member|person|bio|people|about|profile|employee|director|partner|founder|executive|leadership',
    re.IGNORECASE,
)

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

_NOT_A_NAME = {
    "london", "manchester", "birmingham", "leeds", "bristol", "glasgow",
    "edinburgh", "liverpool", "sheffield", "nottingham", "cardiff",
    "maps", "street", "road", "avenue", "lane", "drive", "close",
    "google", "bing", "yahoo", "facebook", "linkedin", "twitter", "instagram",
    "services", "solutions", "limited", "company", "group", "associates",
    "partners", "practice", "clinic", "centre", "center", "dental", "medical",
    "health", "care", "professional", "business", "enterprise", "enterprises",
    "international", "national", "global", "local",
    "surgery", "hospital", "academy", "school", "college", "university",
    "institute", "trust", "foundation", "charity",
    "the", "and", "for", "with", "our", "all", "more", "including",
    "contact", "about", "home", "new", "view", "get", "find",
    "meet", "team", "staff", "management", "read", "click", "here",
    "learn", "see", "show", "hide", "menu", "nhs", "private",
}

_PROPER_NAME_RE = re.compile(r'^[A-Z][a-z]{1,25}(?:\s[A-Z][a-z]{1,25}){1,3}$')
_DR_NAME_RE = re.compile(
    r'\b((?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor)\.?\s+[A-Z][a-z]{1,25}(?:\s[A-Z][a-z]{1,25}){0,3})'
)
_TEAM_LINK_RE = re.compile(
    r'team|staff|people|about|meet|who-we-are|our-team|leadership|founders|executives',
    re.IGNORECASE,
)


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
    if not text or len(text) > 150:
        return False
    t = text.lower()
    return any(kw in t for kw in DM_TITLES)


def _clean(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _extract_from_soup(soup: BeautifulSoup) -> list[dict]:
    contacts: list[dict] = []
    seen: set[str] = set()

    def add(name: str, title: str, source: str = "team_page"):
        name = _clean(name)
        title = _clean(title)
        if name and name not in seen and _is_valid_name(name):
            seen.add(name)
            contacts.append({"name": name, "title": title or "Team Member", "source": source})

    # ── Strategy 1: Schema.org JSON-LD ───────────────────────────────────
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Unwrap @graph
                if item.get("@type") == "WebSite" or "@graph" in item:
                    items = item.get("@graph", [])
                    break
            for item in items:
                t = item.get("@type", "")
                if "Person" in t or "Employee" in t or "Physician" in t:
                    name = item.get("name", "")
                    title = item.get("jobTitle", "") or item.get("description", "")[:60]
                    if name:
                        add(name, title, "team_page")
        except Exception:
            pass

    # ── Strategy 2: Schema.org microdata ─────────────────────────────────
    for el in soup.find_all(attrs={"itemtype": re.compile(r'Person', re.I)}):
        name_el = el.find(attrs={"itemprop": "name"})
        job_el = el.find(attrs={"itemprop": re.compile(r'jobTitle|title', re.I)})
        if name_el:
            add(name_el.get_text(),
                job_el.get_text() if job_el else "", "team_page")

    # ── Strategy 3: Team-hinted CSS containers ────────────────────────────
    for el in soup.find_all(['div', 'article', 'section', 'li']):
        classes = ' '.join(el.get('class', []))
        el_id = el.get('id', '')
        if not _TEAM_HINTS.search(classes + ' ' + el_id):
            continue
        for heading_tag in ['h1', 'h2', 'h3', 'h4', 'h5']:
            for h in el.find_all(heading_tag):
                name_text = _clean(h.get_text())
                # Collect nearby text as potential titles
                title_candidates = []
                for sib in h.next_siblings:
                    if isinstance(sib, Tag):
                        title_candidates.append(_clean(sib.get_text()))
                        break
                for child in el.find_all(['p', 'span', 'small', 'em', 'div']):
                    t = _clean(child.get_text())
                    if t and len(t) < 120:
                        title_candidates.append(t)
                title = next((t for t in title_candidates if _is_title_like(t)), "")
                # Accept even without title if name has Dr/Prof prefix
                if not title and name_text.startswith(("Dr", "Prof")):
                    title = "Professional"
                if title or _is_valid_name(name_text):
                    add(name_text, title)

    # ── Strategy 4: Heading → next sibling ───────────────────────────────
    for heading_tag in ['h2', 'h3', 'h4']:
        for h in soup.find_all(heading_tag):
            name_text = _clean(h.get_text())
            # Also accept "Dr Name" patterns
            if not _is_valid_name(name_text):
                dr_m = _DR_NAME_RE.match(name_text)
                if not dr_m:
                    continue
                name_text = dr_m.group(1)
            for sib in h.next_siblings:
                if not isinstance(sib, Tag):
                    continue
                sib_text = _clean(sib.get_text())
                if _is_title_like(sib_text) and len(sib_text) < 120:
                    add(name_text, sib_text)
                break

    # ── Strategy 5: Dr./Prof. prefix anywhere ────────────────────────────
    full_text = soup.get_text(" ")
    for m in _DR_NAME_RE.finditer(full_text):
        candidate = _clean(m.group(1))
        plain = re.sub(r'^(?:Dr|Mr|Mrs|Ms|Miss|Prof|Professor)\.?\s+', '', candidate)
        if not _is_valid_name(plain):
            continue
        # Look for a title keyword in surrounding text
        start = max(0, m.start() - 80)
        end = min(len(full_text), m.end() + 120)
        context = full_text[start:end]
        title = ""
        for kw in DM_TITLES:
            if kw in context.lower():
                idx = context.lower().find(kw)
                title = _clean(context[max(0, idx-5):idx+40])
                break
        if not title:
            title = "Professional"
        add(candidate, title)

    contacts.sort(key=lambda c: _title_priority(c["title"]))
    return contacts


async def _fetch_page(client: httpx.AsyncClient, url: str) -> Optional[BeautifulSoup]:
    try:
        resp = await client.get(url, timeout=10, follow_redirects=True)
        if not resp.is_success:
            return None
        ct = resp.headers.get("content-type", "")
        if "html" not in ct and "text" not in ct:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def _find_team_links(soup: BeautifulSoup, base: str) -> list[str]:
    """Scan homepage nav/footer for links to team/about pages."""
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text().strip().lower()
        if not href or href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        if _TEAM_LINK_RE.search(href) or _TEAM_LINK_RE.search(text):
            if href.startswith("/"):
                href = base + href
            elif not href.startswith("http"):
                href = base + "/" + href
            if href not in seen:
                seen.add(href)
                links.append(href)
    return links[:8]


async def scrape_team_page(
    domain: str,
    website: str = "",
    max_contacts: int = 5,
) -> list[dict]:
    """
    Try homepage link discovery + common paths to extract person contacts.
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
    tried_urls: set[str] = set()

    def merge(new_contacts: list[dict]):
        for c in new_contacts:
            if c["name"] not in seen_names:
                seen_names.add(c["name"])
                all_contacts.append(c)

    async with httpx.AsyncClient(headers=headers) as client:
        # Step 1: fetch homepage to find team page links
        homepage = await _fetch_page(client, base)
        if homepage:
            # Try homepage itself first (some small businesses list staff on homepage)
            merge(_extract_from_soup(homepage))
            if len(all_contacts) < max_contacts:
                # Find links to team/about pages
                team_links = _find_team_links(homepage, base)
                for url in team_links:
                    if url in tried_urls or len(all_contacts) >= max_contacts:
                        break
                    tried_urls.add(url)
                    soup = await _fetch_page(client, url)
                    if soup:
                        merge(_extract_from_soup(soup))

        # Step 2: try standard paths
        for path in TEAM_PATHS:
            if len(all_contacts) >= max_contacts:
                break
            url = base + path
            if url in tried_urls:
                continue
            tried_urls.add(url)
            soup = await _fetch_page(client, url)
            if soup:
                found = _extract_from_soup(soup)
                merge(found)

    all_contacts.sort(key=lambda c: _title_priority(c["title"]))
    return all_contacts[:max_contacts]

"""
Tier 1b — Email pattern guesser + SMTP verification (free, unlimited)

Tries common email patterns for a domain, then SMTP-verifies each one.
No API needed — connects directly to the domain's mail server.

Patterns tried (in priority order):
  Generic business addresses first (fast, high hit rate for small biz)
  Then decision-maker title patterns
"""

import asyncio
import smtplib
import socket
from typing import Optional
import dns.resolver

GENERIC_PATTERNS = [
    "info",
    "contact",
    "hello",
    "enquiries",
    "admin",
    "office",
    "sales",
    "support",
    "team",
    "help",
]

DECISION_MAKER_PATTERNS = [
    "owner",
    "ceo",
    "director",
    "manager",
    "founder",
    "md",
    "partners",
    "partner",
]

# All patterns combined in priority order
ALL_PATTERNS = GENERIC_PATTERNS + DECISION_MAKER_PATTERNS


def _get_mx_host(domain: str) -> Optional[str]:
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=5)
        return str(sorted(records, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception:
        return None


def _smtp_check(email: str, mx_host: str, from_email: str = "check@verify.com") -> bool:
    """Return True if SMTP server says the mailbox exists."""
    try:
        with smtplib.SMTP(timeout=8) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo_or_helo_if_needed()
            smtp.mail(from_email)
            code, _ = smtp.rcpt(email)
            return code == 250
    except Exception:
        return False


async def guess_email_for_domain(domain: str) -> dict:
    """
    Try all patterns against the domain and SMTP-verify each.
    Returns the first verified hit.
    """
    # Get MX host once
    mx_host = await asyncio.to_thread(_get_mx_host, domain)
    if not mx_host:
        return {"status": "not_found", "source": "pattern_guess"}

    for pattern in ALL_PATTERNS:
        email = f"{pattern}@{domain}"
        valid = await asyncio.to_thread(_smtp_check, email, mx_host)
        if valid:
            is_generic = pattern in GENERIC_PATTERNS
            return {
                "status": "found",
                "email": email,
                "name": None,
                "title": pattern.title() if not is_generic else None,
                "confidence": 55 if is_generic else 65,
                "source": "pattern_guess",
                "pattern": pattern,
            }

    return {"status": "not_found", "source": "pattern_guess"}

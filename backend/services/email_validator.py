"""
Email validation pipeline — runs 4 checks in order, stops at first failure.

1. Syntax      — valid email format
2. MX          — domain has a mail server (DNS lookup, free)
3. Disposable  — reject throwaway email services
4. SMTP        — connect to mail server and verify the mailbox exists (free)

Result grades:
  valid      — safe to send (green)
  risky      — passed MX but SMTP inconclusive (yellow — send with caution)
  invalid    — hard failure, skip this lead (red)
"""

import asyncio
import re
import smtplib
import socket
from typing import Literal

import dns.resolver

DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "throwaway.email", "guerrillamail.com",
    "sharklasers.com", "guerrillamailblock.com", "grr.la", "guerrillamail.info",
    "guerrillamail.biz", "guerrillamail.de", "guerrillamail.net", "guerrillamail.org",
    "spam4.me", "trashmail.com", "trashmail.me", "trashmail.net", "dispostable.com",
    "yopmail.com", "maildrop.cc", "fakeinbox.com", "mailnull.com", "spamgourmet.com",
    "trashmail.at", "trashmail.io", "discard.email", "spamherelots.com",
    "spamhereplease.com", "jetable.fr.nf", "nomail.xl.cx", "mega.zik.dj",
    "speed.1s.fr", "courriel.fr.nf", "moncourrier.fr.nf", "monemail.fr.nf",
    "monmail.fr.nf", "10minutemail.com", "10minutemail.net", "10minutemail.org",
    "minutemail.com", "tempinbox.com", "tempinbox.co.uk", "spambox.us",
    "filzmail.com", "throwam.com", "wegwerfmail.de", "wegwerfmail.net",
    "wegwerfmail.org", "wegwerfemail.de", "emailondeck.com", "getairmail.com",
}

EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')

Grade = Literal["valid", "risky", "invalid"]


def _check_syntax(email: str) -> tuple[bool, str]:
    if not email or not EMAIL_REGEX.match(email):
        return False, "invalid_syntax"
    return True, "ok"


def _check_mx(domain: str) -> tuple[bool, str]:
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=5)
        if not records:
            return False, "no_mx_records"
        return True, "ok"
    except dns.resolver.NXDOMAIN:
        return False, "domain_not_found"
    except dns.resolver.NoAnswer:
        return False, "no_mx_records"
    except Exception:
        return False, "mx_lookup_failed"


def _check_disposable(domain: str) -> tuple[bool, str]:
    if domain.lower() in DISPOSABLE_DOMAINS:
        return False, "disposable_email"
    return True, "ok"


def _smtp_verify(email: str, domain: str, from_email: str = "verify@example.com") -> tuple[Grade, str]:
    """
    SMTP handshake verification — no email is sent.
    Connects to the mail server, says EHLO, then RCPT TO and reads the response.
    250 = mailbox exists, 550/551/553 = doesn't exist, anything else = risky.
    """
    try:
        records = dns.resolver.resolve(domain, "MX", lifetime=5)
        mx_host = str(sorted(records, key=lambda r: r.preference)[0].exchange).rstrip(".")
    except Exception:
        return "risky", "mx_lookup_failed"

    try:
        with smtplib.SMTP(timeout=10) as smtp:
            smtp.connect(mx_host, 25)
            smtp.ehlo_or_helo_if_needed()
            smtp.mail(from_email)
            code, _ = smtp.rcpt(email)

            if code == 250:
                return "valid", "smtp_ok"
            elif code in (550, 551, 552, 553, 554):
                return "invalid", f"smtp_rejected_{code}"
            else:
                # 450/451/452 = temporary failure, 421 = service unavailable
                # Treat as risky — don't hard-fail
                return "risky", f"smtp_temporary_{code}"
    except smtplib.SMTPConnectError:
        return "risky", "smtp_connect_failed"
    except smtplib.SMTPServerDisconnected:
        return "risky", "smtp_disconnected"
    except socket.timeout:
        return "risky", "smtp_timeout"
    except Exception as e:
        return "risky", f"smtp_error"


async def validate_email(email: str) -> dict:
    """
    Full validation pipeline. Returns:
    {
        "grade": "valid" | "risky" | "invalid",
        "reason": str,
        "checks": { syntax, mx, disposable, smtp }
    }
    """
    checks = {}

    # 1. Syntax
    ok, reason = _check_syntax(email)
    checks["syntax"] = {"passed": ok, "reason": reason}
    if not ok:
        return {"grade": "invalid", "reason": reason, "checks": checks}

    domain = email.split("@")[1].lower()

    # 2. Disposable
    ok, reason = _check_disposable(domain)
    checks["disposable"] = {"passed": ok, "reason": reason}
    if not ok:
        return {"grade": "invalid", "reason": reason, "checks": checks}

    # 3. MX (run in thread — dns.resolver is sync)
    ok, reason = await asyncio.to_thread(_check_mx, domain)
    checks["mx"] = {"passed": ok, "reason": reason}
    if not ok:
        return {"grade": "invalid", "reason": reason, "checks": checks}

    # 4. SMTP verify (run in thread — smtplib is sync)
    grade, reason = await asyncio.to_thread(_smtp_verify, email, domain)
    checks["smtp"] = {"passed": grade != "invalid", "reason": reason}

    return {"grade": grade, "reason": reason, "checks": checks}


async def validate_emails_bulk(emails: list[tuple[int, str]]) -> list[dict]:
    """Validate a list of (lead_id, email) pairs concurrently with a semaphore to avoid overwhelming mail servers."""
    sem = asyncio.Semaphore(5)  # max 5 concurrent SMTP connections

    async def _validate_one(lead_id: int, email: str) -> dict:
        async with sem:
            result = await validate_email(email)
            return {"lead_id": lead_id, **result}

    return await asyncio.gather(*[_validate_one(lid, em) for lid, em in emails])

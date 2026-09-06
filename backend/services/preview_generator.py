"""
AI-powered website preview generator.

Takes a lead's business data and generates a complete, professional HTML page
that looks like a real website for that business. Used as the sales pitch —
the prospect sees exactly what their site could look like.

Requires ANTHROPIC_API_KEY in .env.
"""

import httpx
import json
import re

CLAUDE_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-sonnet-4-5"


async def generate_website_preview(
    business_name: str,
    category: str = "",
    location: str = "",
    phone: str = "",
    address: str = "",
    rating: float = 0,
    review_count: int = 0,
    website: str = "",
    api_key: str = "",
) -> str:
    """
    Generate a complete HTML website preview for a business using Claude.
    Returns the full HTML string, or raises on failure.
    """
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not configured")

    loc_display = location or (address.split(",")[-1].strip() if address else "")
    rating_str = f"{rating} stars ({review_count} reviews)" if rating else "highly rated"

    prompt = f"""You are a professional web designer. Create a complete, modern, mobile-responsive single-page website for this local business.

Business details:
- Name: {business_name}
- Type: {category or "local business"}
- Location: {loc_display}
- Phone: {phone or "available on request"}
- Address: {address or loc_display}
- Rating: {rating_str}
- Existing website: {"None" if not website else website}

Requirements:
1. Write a COMPLETE, self-contained HTML file (no external dependencies except Google Fonts via @import)
2. Professional, modern design — NOT generic or template-looking
3. Colour scheme appropriate for the business type
4. Sections: Hero, Services, Why Choose Us, Reviews (fabricate 3 realistic ones based on the category), Service Areas, Contact + CTA
5. Click-to-call button prominent on mobile
6. A banner at the very top saying: "⚡ This is a FREE preview — claim your finished site today"
7. The banner should be styled in a contrasting accent colour and link to nothing (href="#")
8. All placeholder content should sound real and specific to this type of business in this location
9. Include a sticky header with business name and phone number
10. Mobile-first responsive design using CSS Grid/Flexbox

Output ONLY the raw HTML. No explanation, no markdown, no code fences. Start with <!DOCTYPE html>"""

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": MODEL,
        "max_tokens": 8000,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(CLAUDE_API_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    html = data["content"][0]["text"].strip()

    # Strip any accidental markdown fences
    html = re.sub(r"^```html?\s*", "", html, flags=re.MULTILINE)
    html = re.sub(r"```\s*$", "", html, flags=re.MULTILINE)

    return html.strip()

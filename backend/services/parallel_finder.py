"""
Parallel.ai Task API — deep web research fallback for people finder.

Used as the last resort when team page scraper + Brave Search both return nothing.
Costs $0.005–$2.4 per request depending on research depth.
We use a tight prompt to keep it on the cheap end (~$0.005–$0.05).

Docs: https://docs.parallel.ai
"""

import asyncio
import httpx

PARALLEL_TASK_URL = "https://api.parallel.ai/v1/tasks"

# Output schema we ask Parallel to fill
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "contacts": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "name":  {"type": "string", "description": "Full name of the person"},
                    "title": {"type": "string", "description": "Job title or role"},
                },
                "required": ["name", "title"],
            },
        },
    },
    "required": ["contacts"],
}


async def parallel_find_people(
    business_name: str,
    location: str = "",
    domain: str = "",
    api_key: str = "",
    max_contacts: int = 5,
) -> list[dict]:
    """
    Ask Parallel.ai to find decision-makers for a business via deep web research.
    Returns list of {name, title, source: "parallel"} or [] on failure.
    """
    if not api_key:
        return []

    loc_part = f" located in {location}" if location else ""
    domain_part = f" (website: {domain})" if domain else ""

    prompt = (
        f"Find the owners, directors, founders, or senior managers of the business "
        f'"{business_name}"{loc_part}{domain_part}. '
        f"Return up to {max_contacts} real people who run or manage this business, "
        f"with their full name and job title. Only include people directly associated "
        f"with this specific business — do not guess or invent names."
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "prompt": prompt,
        "output_schema": _OUTPUT_SCHEMA,
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            # Submit task
            resp = await client.post(PARALLEL_TASK_URL, json=payload, headers=headers)
            resp.raise_for_status()
            task = resp.json()

        task_id = task.get("id")
        if not task_id:
            return []

        # Poll for completion (Task API is async, 5s–30min)
        poll_url = f"{PARALLEL_TASK_URL}/{task_id}"
        for _ in range(24):  # max ~2 minutes polling
            await asyncio.sleep(5)
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(poll_url, headers=headers)
                resp.raise_for_status()
                result = resp.json()

            status = result.get("status")
            if status == "completed":
                contacts = result.get("output", {}).get("contacts", [])
                return [
                    {"name": c["name"], "title": c.get("title", ""), "source": "parallel"}
                    for c in contacts
                    if c.get("name")
                ]
            if status in ("failed", "cancelled"):
                return []

    except Exception:
        return []

    return []

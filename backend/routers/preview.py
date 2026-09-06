"""
Website preview generation and serving.
"""

import secrets
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from database import get_db
from models import Lead
from services.preview_generator import generate_website_preview
from config import get_settings

router = APIRouter()


@router.post("/api/leads/{lead_id}/generate-preview")
async def generate_preview(lead_id: int, db: Session = Depends(get_db)):
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY not configured")

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    html = await generate_website_preview(
        business_name=lead.business_name,
        category=lead.category or "",
        location="",
        phone=lead.phone or "",
        address=lead.address or "",
        rating=lead.rating or 0,
        review_count=lead.review_count or 0,
        website=lead.website or "",
        api_key=settings.anthropic_api_key,
    )

    if not lead.preview_token:
        lead.preview_token = secrets.token_urlsafe(32)

    lead.preview_html = html
    lead.preview_generated_at = datetime.utcnow()
    db.commit()

    return {"token": lead.preview_token, "url": f"/preview/{lead.preview_token}"}


@router.get("/preview/{token}", response_class=HTMLResponse)
def serve_preview(token: str, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.preview_token == token).first()
    if not lead or not lead.preview_html:
        raise HTTPException(status_code=404, detail="Preview not found")
    return HTMLResponse(content=lead.preview_html)

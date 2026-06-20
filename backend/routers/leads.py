from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import get_db
from models import Lead
from config import get_settings
from services.google_maps import search_businesses
from services.email_finder import find_emails_for_domain

router = APIRouter(prefix="/api/leads", tags=["leads"])
settings = get_settings()


class ScrapeRequest(BaseModel):
    keyword: str
    location: str
    max_results: int = 20


class LeadUpdate(BaseModel):
    status: Optional[str] = None
    notes: Optional[str] = None
    decision_maker_name: Optional[str] = None
    decision_maker_email: Optional[str] = None
    decision_maker_title: Optional[str] = None


@router.post("/scrape")
async def scrape_leads(req: ScrapeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Scrape Google Maps for businesses and save new leads to the DB."""
    if not settings.google_maps_api_key:
        raise HTTPException(status_code=400, detail="GOOGLE_MAPS_API_KEY not set")

    try:
        businesses = await search_businesses(req.keyword, req.location, settings.google_maps_api_key, req.max_results)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Google Maps API error: {e}")

    added, skipped = 0, 0
    for biz in businesses:
        existing = db.query(Lead).filter(Lead.google_place_id == biz["google_place_id"]).first()
        if existing:
            skipped += 1
            continue
        lead = Lead(**{k: v for k, v in biz.items() if hasattr(Lead, k)})
        db.add(lead)
        added += 1

    db.commit()
    return {"added": added, "skipped": skipped, "total_found": len(businesses)}


@router.post("/{lead_id}/find-email")
async def find_email(lead_id: int, db: Session = Depends(get_db)):
    """Run Hunter.io domain search for a single lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.domain:
        raise HTTPException(status_code=400, detail="Lead has no domain — add a website first")
    if not settings.hunter_api_key:
        raise HTTPException(status_code=400, detail="HUNTER_API_KEY not set")

    result = await find_emails_for_domain(lead.domain, settings.hunter_api_key)

    if result["status"] == "found":
        lead.decision_maker_email = result["email"]
        lead.decision_maker_name = result.get("name")
        lead.decision_maker_title = result.get("title")
        lead.email_confidence = result.get("confidence")
        lead.email_status = "found"
    else:
        lead.email_status = "not_found"

    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return {"status": result["status"], "lead": _lead_dict(lead)}


@router.post("/find-emails-bulk")
async def find_emails_bulk(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue email lookup for all leads with a domain but no email yet."""
    if not settings.hunter_api_key:
        raise HTTPException(status_code=400, detail="HUNTER_API_KEY not set")

    leads = db.query(Lead).filter(
        Lead.domain.isnot(None),
        Lead.email_status == "not_searched"
    ).all()

    if not leads:
        return {"message": "No leads to process", "queued": 0}

    background_tasks.add_task(_bulk_email_search, [l.id for l in leads])
    return {"message": f"Queued {len(leads)} leads for email lookup", "queued": len(leads)}


async def _bulk_email_search(lead_ids: list[int]):
    from database import SessionLocal
    db = SessionLocal()
    try:
        for lead_id in lead_ids:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead or not lead.domain:
                continue
            result = await find_emails_for_domain(lead.domain, settings.hunter_api_key)
            if result["status"] == "found":
                lead.decision_maker_email = result["email"]
                lead.decision_maker_name = result.get("name")
                lead.decision_maker_title = result.get("title")
                lead.email_confidence = result.get("confidence")
                lead.email_status = "found"
            else:
                lead.email_status = "not_found"
            lead.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.get("")
def list_leads(
    status: Optional[str] = None,
    email_status: Optional[str] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Lead)
    if status:
        q = q.filter(Lead.status == status)
    if email_status:
        q = q.filter(Lead.email_status == email_status)
    if search:
        q = q.filter(or_(
            Lead.business_name.ilike(f"%{search}%"),
            Lead.address.ilike(f"%{search}%"),
            Lead.decision_maker_email.ilike(f"%{search}%"),
        ))
    total = q.count()
    leads = q.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "leads": [_lead_dict(l) for l in leads]}


@router.get("/{lead_id}")
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return _lead_dict(lead)


@router.patch("/{lead_id}")
def update_lead(lead_id: int, update: LeadUpdate, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    for field, value in update.model_dump(exclude_none=True).items():
        setattr(lead, field, value)
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return _lead_dict(lead)


@router.delete("/{lead_id}")
def delete_lead(lead_id: int, db: Session = Depends(get_db)):
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    db.delete(lead)
    db.commit()
    return {"ok": True}


def _lead_dict(lead: Lead) -> dict:
    return {
        "id": lead.id,
        "business_name": lead.business_name,
        "address": lead.address,
        "phone": lead.phone,
        "website": lead.website,
        "domain": lead.domain,
        "category": lead.category,
        "rating": lead.rating,
        "review_count": lead.review_count,
        "maps_url": lead.maps_url,
        "decision_maker_name": lead.decision_maker_name,
        "decision_maker_email": lead.decision_maker_email,
        "decision_maker_title": lead.decision_maker_title,
        "email_confidence": lead.email_confidence,
        "email_status": lead.email_status,
        "status": lead.status,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import get_db
from models import Lead, ScrapeJob, LeadContact
from config import get_settings
from services.google_maps import search_businesses, grid_search_businesses, deep_search_businesses
from services.email_chain import find_email_chain
from services.email_validator import validate_email, validate_emails_bulk
from services.people_finder import find_decision_maker, find_decision_makers

router = APIRouter(prefix="/api/leads", tags=["leads"])
settings = get_settings()


class ScrapeRequest(BaseModel):
    keyword: str
    location: str
    max_results: int = 20


class GridScrapeRequest(BaseModel):
    keyword: str
    location: str
    square_size: int = 2000  # meters — 2000 covers ~12x12km, 5000 covers ~30x30km
    mode: str = "grid"       # grid (36 viewports) | deep (324 viewports, 9 centers)
    max_items: int = 0       # 0 = unlimited, mirrors n8n's max_items param


class SmartScrapeRequest(BaseModel):
    keyword: str
    location: str
    target: int = 100        # desired number of NEW leads added to the DB


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


@router.post("/scrape-grid")
async def scrape_grid(req: GridScrapeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Grid scrape (mode=grid: 36 viewports) or Deep Sweep (mode=deep: 216 viewports, 6 centers).
    Runs in background. Poll /scrape-jobs/{id} for progress.
    """
    if not settings.google_maps_api_key:
        raise HTTPException(status_code=400, detail="GOOGLE_MAPS_API_KEY not set")

    is_deep = req.mode == "deep"
    viewports_total = 324 if is_deep else 36   # 9 centers × 36 or 1 center × 36
    mode_label = "deep" if is_deep else "grid"

    job = ScrapeJob(
        keyword=req.keyword,
        location=req.location,
        mode=mode_label,
        square_size=req.square_size,
        viewports_total=viewports_total,
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_grid_scrape, job.id, req.keyword, req.location, req.square_size, is_deep, req.max_items)
    msg = f"{'Deep Sweep' if is_deep else 'Grid scrape'} started — {viewports_total} viewports queued"
    return {"job_id": job.id, "message": msg, "viewports_total": viewports_total, "mode": mode_label}


@router.post("/smart-scrape")
async def smart_scrape(req: SmartScrapeRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Auto-scaling scrape: expands radius pass-by-pass until the target lead count is reached."""
    if not settings.google_maps_api_key:
        raise HTTPException(status_code=400, detail="GOOGLE_MAPS_API_KEY not set")

    job = ScrapeJob(
        keyword=req.keyword,
        location=req.location,
        mode="smart",
        square_size=0,
        viewports_total=36,   # updated per-pass as we go
        status="running",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(_run_smart_scrape, job.id, req.keyword, req.location, req.target)
    return {"job_id": job.id, "message": f"Smart scrape started — target {req.target} leads", "mode": "smart"}


@router.get("/scrape-jobs/{job_id}")
def get_scrape_job(job_id: int, db: Session = Depends(get_db)):
    """Poll this endpoint for grid scrape progress."""
    job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    is_running = job.status == "running"
    return {
        "id": job.id,
        "status": job.status,
        "keyword": job.keyword,
        "location": job.location,
        "square_size": job.square_size,
        "viewports_done": job.viewports_done,
        "viewports_total": job.viewports_total,
        "progress_pct": round((job.viewports_done / job.viewports_total) * 100) if job.viewports_total else 0,
        "leads_found": job.leads_found,
        "leads_added": job.leads_added,
        "pass_label": job.error if is_running else None,
        "error": job.error if not is_running else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/scrape-jobs")
def list_scrape_jobs(db: Session = Depends(get_db)):
    jobs = db.query(ScrapeJob).order_by(ScrapeJob.created_at.desc()).limit(20).all()
    return [
        {
            "id": j.id, "keyword": j.keyword, "location": j.location,
            "mode": j.mode, "status": j.status,
            "viewports_done": j.viewports_done, "viewports_total": j.viewports_total,
            "leads_added": j.leads_added, "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


async def _run_grid_scrape(job_id: int, keyword: str, location: str, square_size: int, deep: bool = False, max_items: int = 0):
    from database import SessionLocal
    db = SessionLocal()

    async def _progress(done: int, total: int, found: int):
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.viewports_done = done
            job.leads_found = found
            db.commit()

    try:
        fn = deep_search_businesses if deep else grid_search_businesses
        businesses = await fn(keyword, location, settings.google_maps_api_key, square_size, max_items, _progress)

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

        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.status = "done"
            job.leads_added = added
            job.leads_found = len(businesses)
            job.viewports_done = job.viewports_total
            job.finished_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


_SMART_PASSES = [
    ("grid", 1000,  36,  "Pass 1/4 — grid, 1 km radius"),
    ("grid", 3000,  36,  "Pass 2/4 — grid, 3 km radius"),
    ("deep", 2000, 324,  "Pass 3/4 — deep sweep, 2 km"),
    ("deep", 5000, 324,  "Pass 4/4 — deep sweep, 5 km"),
]


async def _run_smart_scrape(job_id: int, keyword: str, location: str, target: int):
    from database import SessionLocal
    db = SessionLocal()

    viewports_offset = 0
    total_added = 0
    total_found = 0

    try:
        for mode, square_size, vp_count, label in _SMART_PASSES:
            job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
            if job:
                job.error = label
                job.viewports_total = viewports_offset + vp_count
                db.commit()

            async def _progress(done: int, total: int, found: int, _off=viewports_offset):
                j = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
                if j:
                    j.viewports_done = _off + done
                    j.leads_found = total_found + found
                    db.commit()

            fn = deep_search_businesses if mode == "deep" else grid_search_businesses
            results = await fn(keyword, location, settings.google_maps_api_key, square_size, target, _progress)

            added = 0
            for biz in results:
                existing = db.query(Lead).filter(Lead.google_place_id == biz["google_place_id"]).first()
                if not existing:
                    db.add(Lead(**{k: v for k, v in biz.items() if hasattr(Lead, k)}))
                    added += 1
            db.commit()

            total_added += added
            total_found += len(results)
            viewports_offset += vp_count

            if target > 0 and total_added >= target:
                break

        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.status = "done"
            job.leads_added = total_added
            job.leads_found = total_found
            job.viewports_done = viewports_offset
            job.error = None
            job.finished_at = datetime.utcnow()
            db.commit()

    except Exception as e:
        job = db.query(ScrapeJob).filter(ScrapeJob.id == job_id).first()
        if job:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.post("/{lead_id}/find-person")
async def find_person(lead_id: int, db: Session = Depends(get_db)):
    """Use Brave Search to find up to 5 decision-makers for a single lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not settings.brave_api_key:
        raise HTTPException(status_code=400, detail="BRAVE_API_KEY not set")

    result = await find_decision_makers(
        business_name=lead.business_name,
        location=lead.address or "",
        domain=lead.domain or "",
        api_key=settings.brave_api_key,
        max_contacts=5,
    )

    if result["status"] == "found":
        # Clear old contacts for this lead
        db.query(LeadContact).filter(LeadContact.lead_id == lead_id).delete()
        for rank, c in enumerate(result["contacts"], start=1):
            db.add(LeadContact(
                lead_id=lead_id,
                rank=rank,
                name=c["name"],
                title=c["title"],
                source=c["source"],
            ))
        # Keep primary contact on Lead for backwards compat
        primary = result["contacts"][0]
        lead.decision_maker_name = primary["name"]
        lead.decision_maker_title = primary["title"]
        lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(lead)

    return {"status": result["status"], "source": result["source"], "lead": _lead_dict(lead)}


@router.post("/find-persons-bulk")
async def find_persons_bulk(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue Brave Search people lookup for all leads missing a decision-maker name."""
    if not settings.brave_api_key:
        raise HTTPException(status_code=400, detail="BRAVE_API_KEY not set")

    leads = db.query(Lead).filter(Lead.decision_maker_name.is_(None)).all()
    if not leads:
        return {"message": "No leads to process", "queued": 0}

    background_tasks.add_task(_bulk_find_persons, [l.id for l in leads])
    return {"message": f"Queued {len(leads)} leads for people lookup", "queued": len(leads)}


async def _bulk_find_persons(lead_ids: list[int]):
    from database import SessionLocal
    db = SessionLocal()
    try:
        for lead_id in lead_ids:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                continue
            result = await find_decision_makers(
                business_name=lead.business_name,
                location=lead.address or "",
                domain=lead.domain or "",
                api_key=settings.brave_api_key,
                max_contacts=5,
            )
            if result["status"] == "found":
                db.query(LeadContact).filter(LeadContact.lead_id == lead_id).delete()
                for rank, c in enumerate(result["contacts"], start=1):
                    db.add(LeadContact(
                        lead_id=lead_id,
                        rank=rank,
                        name=c["name"],
                        title=c["title"],
                        source=c["source"],
                    ))
                primary = result["contacts"][0]
                lead.decision_maker_name = primary["name"]
                lead.decision_maker_title = primary["title"]
                lead.updated_at = datetime.utcnow()
                db.commit()
    finally:
        db.close()


@router.post("/{lead_id}/find-email")
async def find_email(lead_id: int, db: Session = Depends(get_db)):
    """Run full email finder chain for a single lead (website → pattern → APIs)."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.domain:
        raise HTTPException(status_code=400, detail="Lead has no domain — add a website first")

    result = await find_email_chain(lead.domain, lead.website or "")

    if result["status"] == "found":
        lead.decision_maker_email = result["email"]
        lead.decision_maker_name = result.get("name")
        lead.decision_maker_title = result.get("title")
        lead.email_confidence = result.get("confidence")
        lead.email_status = "found"
        lead.email_source = result.get("source")
    else:
        lead.email_status = "not_found"
        lead.email_source = None

    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return {
        "status": result["status"],
        "source": result.get("source"),
        "tried": result.get("tried", []),
        "lead": _lead_dict(lead),
    }


@router.post("/find-emails-bulk")
async def find_emails_bulk(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Queue email chain for all leads with a domain but no email yet."""

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
            result = await find_email_chain(lead.domain, lead.website or "")
            if result["status"] == "found":
                lead.decision_maker_email = result["email"]
                lead.decision_maker_name = result.get("name")
                lead.decision_maker_title = result.get("title")
                lead.email_confidence = result.get("confidence")
                lead.email_status = "found"
                lead.email_source = result.get("source")
            else:
                lead.email_status = "not_found"
                lead.email_source = None
            lead.updated_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.get("")
def list_leads(
    status: Optional[str] = None,
    email_status: Optional[str] = None,
    email_grade: Optional[str] = None,
    search: Optional[str] = None,
    has_website: Optional[str] = None,
    skip: int = 0,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(Lead)
    if status:
        q = q.filter(Lead.status == status)
    if email_status:
        q = q.filter(Lead.email_status == email_status)
    if email_grade:
        q = q.filter(Lead.email_grade == email_grade)
    if has_website == 'true':
        q = q.filter(Lead.website.isnot(None))
    elif has_website == 'false':
        q = q.filter(Lead.website.is_(None))
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


@router.post("/{lead_id}/validate-email")
async def validate_lead_email(lead_id: int, db: Session = Depends(get_db)):
    """Run full validation pipeline on a single lead's email."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.decision_maker_email:
        raise HTTPException(status_code=400, detail="Lead has no email to validate")

    result = await validate_email(lead.decision_maker_email)

    lead.email_grade = result["grade"]
    lead.email_valid_reason = result["reason"]
    lead.email_validated_at = datetime.utcnow()
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    return {"grade": result["grade"], "reason": result["reason"], "checks": result["checks"], "lead": _lead_dict(lead)}


@router.post("/validate-emails-bulk")
async def validate_emails_bulk_endpoint(
    background_tasks: BackgroundTasks,
    grade_filter: Optional[str] = None,  # only re-validate leads with this grade (or None = all unvalidated)
    db: Session = Depends(get_db),
):
    """Queue email validation for all leads that have an email but no grade yet."""
    q = db.query(Lead).filter(Lead.decision_maker_email.isnot(None))
    if grade_filter:
        q = q.filter(Lead.email_grade == grade_filter)
    else:
        q = q.filter(Lead.email_grade.is_(None))

    leads = q.all()
    if not leads:
        return {"message": "No leads to validate", "queued": 0}

    pairs = [(l.id, l.decision_maker_email) for l in leads]
    background_tasks.add_task(_bulk_validate_bg, pairs)
    return {"message": f"Queued {len(leads)} leads for validation", "queued": len(leads)}


async def _bulk_validate_bg(pairs: list[tuple[int, str]]):
    from database import SessionLocal
    results = await validate_emails_bulk(pairs)
    db = SessionLocal()
    try:
        for r in results:
            lead = db.query(Lead).filter(Lead.id == r["lead_id"]).first()
            if not lead:
                continue
            lead.email_grade = r["grade"]
            lead.email_valid_reason = r["reason"]
            lead.email_validated_at = datetime.utcnow()
            lead.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _contact_dict(c: LeadContact) -> dict:
    return {
        "id": c.id,
        "rank": c.rank,
        "name": c.name,
        "title": c.title,
        "email": c.email,
        "email_status": c.email_status,
        "email_source": c.email_source,
        "email_grade": c.email_grade,
        "email_valid_reason": c.email_valid_reason,
        "source": c.source,
    }


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
        "email_source": lead.email_source,
        "email_grade": lead.email_grade,
        "email_valid_reason": lead.email_valid_reason,
        "email_validated_at": lead.email_validated_at.isoformat() if lead.email_validated_at else None,
        "status": lead.status,
        "notes": lead.notes,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "contacts": [_contact_dict(c) for c in lead.contacts] if lead.contacts else [],
    }

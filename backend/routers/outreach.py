import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db
from models import Campaign, EmailLog, Lead
from services.email_sender import render_template, send_email

router = APIRouter(prefix="/api/outreach", tags=["outreach"])
settings = get_settings()


class SendRequest(BaseModel):
    campaign_id: int
    lead_ids: Optional[list[int]] = None  # None = all leads with emails in the campaign's target
    filter_status: Optional[str] = "new"  # only send to leads with this status


class PreviewRequest(BaseModel):
    campaign_id: int
    lead_id: int


@router.post("/preview")
def preview_email(req: PreviewRequest, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == req.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    ctx = _lead_context(lead)
    subject = render_template(campaign.subject, ctx)
    body = render_template(campaign.body, ctx)
    return {"to": lead.decision_maker_email, "subject": subject, "body": body}


@router.post("/send")
async def send_campaign(req: SendRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    campaign = db.query(Campaign).filter(Campaign.id == req.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    q = db.query(Lead).filter(Lead.decision_maker_email.isnot(None))
    if req.filter_status:
        q = q.filter(Lead.status == req.filter_status)
    if req.lead_ids:
        q = q.filter(Lead.id.in_(req.lead_ids))

    leads = q.all()
    if not leads:
        raise HTTPException(status_code=400, detail="No eligible leads found (need email + matching status)")

    # Check daily cap
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    sent_today = db.query(EmailLog).filter(
        EmailLog.status == "sent",
        EmailLog.sent_at >= today_start,
    ).count()

    remaining_cap = settings.max_emails_per_day - sent_today
    if remaining_cap <= 0:
        raise HTTPException(status_code=429, detail=f"Daily send limit ({settings.max_emails_per_day}) reached")

    leads_to_send = leads[:remaining_cap]

    # Create pending email logs
    log_ids = []
    for lead in leads_to_send:
        ctx = _lead_context(lead)
        log = EmailLog(
            lead_id=lead.id,
            campaign_id=campaign.id,
            to_email=lead.decision_maker_email,
            subject=render_template(campaign.subject, ctx),
            body_preview=render_template(campaign.body, ctx)[:500],
            status="pending",
        )
        db.add(log)
        db.flush()
        log_ids.append(log.id)
    db.commit()

    background_tasks.add_task(
        _send_emails_bg,
        log_ids,
        campaign.send_delay_seconds,
    )

    return {
        "queued": len(log_ids),
        "capped_at": settings.max_emails_per_day,
        "sent_today_before": sent_today,
        "message": f"Sending {len(log_ids)} emails in background with {campaign.send_delay_seconds}s delay between each",
    }


async def _send_emails_bg(log_ids: list[int], delay_seconds: int):
    from database import SessionLocal
    db = SessionLocal()
    try:
        for log_id in log_ids:
            log = db.query(EmailLog).filter(EmailLog.id == log_id).first()
            if not log:
                continue

            result = await send_email(log.to_email, log.subject, log.body_preview)

            if result["success"]:
                log.status = "sent"
                log.sent_at = datetime.utcnow()
                # Update lead status to contacted
                lead = db.query(Lead).filter(Lead.id == log.lead_id).first()
                if lead and lead.status == "new":
                    lead.status = "contacted"
                    lead.updated_at = datetime.utcnow()
            else:
                log.status = "failed"
                log.error_message = result["error"]

            db.commit()

            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
    finally:
        db.close()


@router.get("/logs")
def get_logs(
    campaign_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    q = db.query(EmailLog)
    if campaign_id:
        q = q.filter(EmailLog.campaign_id == campaign_id)
    if lead_id:
        q = q.filter(EmailLog.lead_id == lead_id)
    if status:
        q = q.filter(EmailLog.status == status)
    total = q.count()
    logs = q.order_by(EmailLog.created_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "logs": [_log_dict(l) for l in logs]}


def _lead_context(lead: Lead) -> dict:
    return {
        "business_name": lead.business_name or "",
        "decision_maker_name": lead.decision_maker_name or "",
        "decision_maker_title": lead.decision_maker_title or "",
        "website": lead.website or "",
        "address": lead.address or "",
        "phone": lead.phone or "",
        "category": lead.category or "",
        "domain": lead.domain or "",
    }


def _log_dict(log: EmailLog) -> dict:
    return {
        "id": log.id,
        "lead_id": log.lead_id,
        "campaign_id": log.campaign_id,
        "to_email": log.to_email,
        "subject": log.subject,
        "status": log.status,
        "error_message": log.error_message,
        "sent_at": log.sent_at.isoformat() if log.sent_at else None,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }

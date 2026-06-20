from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta

from database import get_db
from models import Lead, Campaign, EmailLog

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    total_leads = db.query(Lead).count()
    leads_with_email = db.query(Lead).filter(Lead.decision_maker_email.isnot(None)).count()
    contacted = db.query(Lead).filter(Lead.status == "contacted").count()
    replied = db.query(Lead).filter(Lead.status == "replied").count()
    converted = db.query(Lead).filter(Lead.status == "converted").count()

    total_emails_sent = db.query(EmailLog).filter(EmailLog.status == "sent").count()
    total_emails_failed = db.query(EmailLog).filter(EmailLog.status == "failed").count()

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    emails_today = db.query(EmailLog).filter(
        EmailLog.status == "sent",
        EmailLog.sent_at >= today,
    ).count()

    last_7_days = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        next_day = day + timedelta(days=1)
        count = db.query(EmailLog).filter(
            EmailLog.status == "sent",
            EmailLog.sent_at >= day,
            EmailLog.sent_at < next_day,
        ).count()
        last_7_days.append({"date": day.strftime("%b %d"), "sent": count})

    lead_statuses = db.query(Lead.status, func.count(Lead.id)).group_by(Lead.status).all()
    email_statuses = db.query(Lead.email_status, func.count(Lead.id)).group_by(Lead.email_status).all()

    return {
        "leads": {
            "total": total_leads,
            "with_email": leads_with_email,
            "contacted": contacted,
            "replied": replied,
            "converted": converted,
        },
        "emails": {
            "total_sent": total_emails_sent,
            "total_failed": total_emails_failed,
            "sent_today": emails_today,
        },
        "charts": {
            "emails_last_7_days": last_7_days,
            "lead_status_breakdown": [{"status": s, "count": c} for s, c in lead_statuses],
            "email_status_breakdown": [{"status": s, "count": c} for s, c in email_statuses],
        },
    }

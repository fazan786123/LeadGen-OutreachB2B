from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from database import get_db
from models import Campaign

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])

TEMPLATE_VARS_HELP = (
    "Available template variables: {{ business_name }}, {{ decision_maker_name }}, "
    "{{ decision_maker_title }}, {{ website }}, {{ address }}, {{ phone }}, {{ category }}"
)

DEFAULT_TEMPLATE_SUBJECT = "Quick question about {{ business_name }}"
DEFAULT_TEMPLATE_BODY = """Hi {{ decision_maker_name or 'there' }},

I came across {{ business_name }} and was impressed by what you're doing.

I wanted to reach out to see if you'd be open to a quick 15-minute call to explore how we might be able to help {{ business_name }} grow.

Would you be available this week or next?

Best regards,
[Your Name]

P.S. If you're not the right person to speak with, could you point me in the right direction?
"""


class CampaignCreate(BaseModel):
    name: str
    subject: str = DEFAULT_TEMPLATE_SUBJECT
    body: str = DEFAULT_TEMPLATE_BODY
    send_delay_seconds: int = 60


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    status: Optional[str] = None
    send_delay_seconds: Optional[int] = None


@router.post("")
def create_campaign(req: CampaignCreate, db: Session = Depends(get_db)):
    campaign = Campaign(
        name=req.name,
        subject=req.subject,
        body=req.body,
        send_delay_seconds=req.send_delay_seconds,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return _campaign_dict(campaign)


@router.get("")
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return [_campaign_dict(c) for c in campaigns]


@router.get("/template-help")
def template_help():
    return {"help": TEMPLATE_VARS_HELP, "default_subject": DEFAULT_TEMPLATE_SUBJECT, "default_body": DEFAULT_TEMPLATE_BODY}


@router.get("/{campaign_id}")
def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _campaign_dict(c)


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: int, update: CampaignUpdate, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    for field, value in update.model_dump(exclude_none=True).items():
        setattr(c, field, value)
    c.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(c)
    return _campaign_dict(c)


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    db.delete(c)
    db.commit()
    return {"ok": True}


def _campaign_dict(c: Campaign) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "subject": c.subject,
        "body": c.body,
        "status": c.status,
        "send_delay_seconds": c.send_delay_seconds,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }

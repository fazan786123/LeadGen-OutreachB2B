from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean, Float
from sqlalchemy.orm import relationship
from database import Base


class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    business_name = Column(String(255), nullable=False)
    address = Column(Text)
    phone = Column(String(50))
    website = Column(String(255))
    domain = Column(String(255))
    category = Column(String(255))
    rating = Column(Float)
    review_count = Column(Integer)
    google_place_id = Column(String(255), unique=True, index=True)
    maps_url = Column(String(500))
    # Email finder results
    decision_maker_name = Column(String(255))
    decision_maker_email = Column(String(255))
    decision_maker_title = Column(String(255))
    email_confidence = Column(Integer)
    email_status = Column(String(50), default="not_searched")  # not_searched | found | not_found
    email_source = Column(String(50))  # website_scrape | pattern_guess | apollo | snov | skrapp | findthat | hunter
    # Email validation
    email_grade = Column(String(20))       # valid | risky | invalid | None (not validated)
    email_valid_reason = Column(String(100))
    email_validated_at = Column(DateTime)
    # Lead status
    status = Column(String(50), default="new")  # new | contacted | replied | converted | unsubscribed
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    email_logs = relationship("EmailLog", back_populates="lead")
    contacts = relationship("LeadContact", back_populates="lead", order_by="LeadContact.rank")


class LeadContact(Base):
    """Up to 5 decision-maker contacts per lead, ranked by title priority."""
    __tablename__ = "lead_contacts"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    rank = Column(Integer, default=1)  # 1 = primary, 2-5 = secondary
    name = Column(String(255))
    title = Column(String(255))
    email = Column(String(255))
    email_confidence = Column(Integer)
    email_status = Column(String(50), default="not_searched")
    email_source = Column(String(50))
    email_grade = Column(String(20))
    email_valid_reason = Column(String(100))
    source = Column(String(50))  # brave_linkedin | brave_search
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("Lead", back_populates="contacts")


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String(255))
    location = Column(String(255))
    mode = Column(String(20), default="quick")       # quick | grid
    square_size = Column(Integer)                     # meters, grid mode only
    status = Column(String(20), default="running")   # running | done | failed
    viewports_done = Column(Integer, default=0)
    viewports_total = Column(Integer, default=0)
    leads_found = Column(Integer, default=0)
    leads_added = Column(Integer, default=0)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=False)  # Jinja2 template — use {{ business_name }}, {{ decision_maker_name }}, etc.
    status = Column(String(50), default="draft")  # draft | active | paused | completed
    send_delay_seconds = Column(Integer, default=60)  # delay between sends to avoid spam
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    email_logs = relationship("EmailLog", back_populates="campaign")


class EmailLog(Base):
    __tablename__ = "email_logs"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    to_email = Column(String(255), nullable=False)
    subject = Column(String(500))
    body_preview = Column(Text)
    status = Column(String(50), default="pending")  # pending | sent | failed | bounced
    error_message = Column(Text)
    sent_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("Lead", back_populates="email_logs")
    campaign = relationship("Campaign", back_populates="email_logs")

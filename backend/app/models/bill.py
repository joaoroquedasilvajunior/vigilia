import uuid
from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Date, DateTime, Numeric, Text, Boolean, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from .base import Base


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camara_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    type: Mapped[str | None] = mapped_column(String(10))
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary_official: Mapped[str | None] = mapped_column(Text)
    summary_ai: Mapped[str | None] = mapped_column(Text)
    full_text_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(80))
    urgency_regime: Mapped[bool] = mapped_column(Boolean, default=False)
    secrecy_vote: Mapped[bool] = mapped_column(Boolean, default=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("legislators.id"))
    author_type: Mapped[str | None] = mapped_column(String(20), default="legislator")
    presentation_date: Mapped[date | None] = mapped_column(Date)
    final_vote_date: Mapped[date | None] = mapped_column(Date)
    # last_vote_at = MAX(votes.voted_at) for this bill. Maintained by the
    # ingestion pipeline (and the one-shot backfill SQL) so the activity
    # dashboards have a real "recently active" signal — bills.updated_at
    # is touched on every nightly sync and can't be used for that purpose.
    last_vote_at: Mapped[datetime | None] = mapped_column(DateTime)
    const_risk_score: Mapped[float | None] = mapped_column(Float)
    media_coverage_score: Mapped[int] = mapped_column(Integer, default=0)
    theme_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    affected_articles: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    author = relationship("Legislator", foreign_keys=[author_id])

    __table_args__ = (
        CheckConstraint("type IN ('PL','PEC','MPV','PDL','PLP','MSC')", name="ck_bill_type"),
        CheckConstraint("const_risk_score BETWEEN 0 AND 1", name="ck_bill_risk_score"),
    )

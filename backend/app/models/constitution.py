import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, Float, DateTime, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from .base import Base


class ConstitutionArticle(Base):
    __tablename__ = "constitution_articles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    article_ref: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    text_full: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str | None] = mapped_column(String(50))
    theme_tags: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    stf_precedents: Mapped[dict] = mapped_column(JSONB, default=list)
    is_fundamental: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class BillConstitutionMapping(Base):
    __tablename__ = "bill_constitution_mapping"

    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bills.id"), primary_key=True)
    article_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("constitution_articles.id"), primary_key=True
    )
    relationship: Mapped[str | None] = mapped_column(String(20))
    ai_confidence: Mapped[float | None] = mapped_column(Float)
    reviewed_by_expert: Mapped[bool] = mapped_column(Boolean, default=False)
    expert_note: Mapped[str | None] = mapped_column(Text)
    expert_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "relationship IN ('compatible','conflicts','amends','regulates')",
            name="ck_bcm_relationship",
        ),
        CheckConstraint("ai_confidence BETWEEN 0 AND 1", name="ck_bcm_confidence"),
    )

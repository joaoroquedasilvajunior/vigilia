import uuid
from datetime import datetime
from sqlalchemy import Float, Integer, DateTime, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class LegislatorTheme(Base):
    __tablename__ = "legislator_themes"

    legislator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("legislators.id"), primary_key=True
    )
    theme_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("themes.id"), primary_key=True
    )
    votes_favorable: Mapped[int] = mapped_column(Integer, default=0)
    votes_against: Mapped[int] = mapped_column(Integer, default=0)
    abstentions: Mapped[int] = mapped_column(Integer, default=0)
    absences: Mapped[int] = mapped_column(Integer, default=0)
    position_score: Mapped[float | None] = mapped_column(Float)
    last_updated: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    __table_args__ = (
        CheckConstraint("position_score BETWEEN -1 AND 1", name="ck_lt_position_score"),
    )

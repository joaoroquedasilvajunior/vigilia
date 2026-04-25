import uuid
from datetime import date
from sqlalchemy import String, Float, Integer, Date, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Party(Base):
    __tablename__ = "parties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    acronym: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column()
    founded_date: Mapped[date | None] = mapped_column(Date)
    tse_number: Mapped[int | None] = mapped_column(Integer)
    ideological_self: Mapped[str | None] = mapped_column(String(50))
    actual_position: Mapped[float | None] = mapped_column(Float)
    cohesion_score: Mapped[float | None] = mapped_column(Float)
    member_count: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("actual_position BETWEEN -1 AND 1", name="ck_party_actual_position"),
        CheckConstraint("cohesion_score BETWEEN 0 AND 1", name="ck_party_cohesion_score"),
    )

import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legislator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("legislators.id"), nullable=False)
    bill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("bills.id"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("sessions.id"))
    vote_value: Mapped[str | None] = mapped_column(String(15))
    voted_at: Mapped[datetime | None] = mapped_column(DateTime)
    party_orientation: Mapped[str | None] = mapped_column(String(15))
    followed_party_line: Mapped[bool | None] = mapped_column(Boolean)
    donor_conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    const_conflict_flag: Mapped[bool] = mapped_column(Boolean, default=False)

    legislator = relationship("Legislator", foreign_keys=[legislator_id])
    bill = relationship("Bill", foreign_keys=[bill_id])

    __table_args__ = (
        UniqueConstraint("legislator_id", "bill_id", name="uq_vote_legislator_bill"),
        CheckConstraint(
            "vote_value IN ('sim','não','abstencao','obstrucao','ausente')",
            name="ck_vote_value",
        ),
        CheckConstraint(
            "party_orientation IN ('sim','não','livre','obstrucao')",
            name="ck_vote_party_orientation",
        ),
    )

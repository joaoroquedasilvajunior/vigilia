import uuid
from datetime import date, datetime
from sqlalchemy import String, Float, Integer, Date, DateTime, Numeric, Text, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Legislator(Base):
    __tablename__ = "legislators"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camara_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    senado_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    chamber: Mapped[str | None] = mapped_column(String(10))
    state_uf: Mapped[str] = mapped_column(String(2), nullable=False)
    nominal_party_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("parties.id"))
    education_level: Mapped[str | None] = mapped_column(String(100))
    declared_assets_brl: Mapped[float | None] = mapped_column(Numeric(18, 2))
    term_start: Mapped[date | None] = mapped_column(Date)
    term_end: Mapped[date | None] = mapped_column(Date)
    photo_url: Mapped[str | None] = mapped_column(Text)
    cpf_hash: Mapped[str | None] = mapped_column(String(64))
    behavioral_cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("behavioral_clusters.id")
    )
    const_alignment_score: Mapped[float | None] = mapped_column(Float)
    party_discipline_score: Mapped[float | None] = mapped_column(Float)
    absence_rate: Mapped[float | None] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    party = relationship("Party", foreign_keys=[nominal_party_id])
    cluster = relationship("BehavioralCluster", foreign_keys=[behavioral_cluster_id])

    __table_args__ = (
        CheckConstraint("chamber IN ('camara', 'senado')", name="ck_legislator_chamber"),
        CheckConstraint("const_alignment_score BETWEEN -1 AND 1", name="ck_legislator_const_score"),
        CheckConstraint("party_discipline_score BETWEEN 0 AND 1", name="ck_legislator_discipline"),
        CheckConstraint("absence_rate BETWEEN 0 AND 1", name="ck_legislator_absence"),
    )

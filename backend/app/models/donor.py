import uuid
from sqlalchemy import String, Numeric, Integer, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Donor(Base):
    __tablename__ = "donors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cnpj_cpf_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(20))
    sector_cnae: Mapped[str | None] = mapped_column(String(20))
    sector_group: Mapped[str | None] = mapped_column(String(50))
    state_uf: Mapped[str | None] = mapped_column(String(2))
    total_donated_brl: Mapped[float] = mapped_column(Numeric(18, 2), default=0)

    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('pessoa_fisica','pessoa_juridica')",
            name="ck_donor_entity_type",
        ),
    )


class DonorLink(Base):
    __tablename__ = "donor_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legislator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("legislators.id"), nullable=False)
    donor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("donors.id"), nullable=False)
    amount_brl: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    election_year: Mapped[int] = mapped_column(Integer, nullable=False)
    donation_type: Mapped[str | None] = mapped_column(String(50))
    source_doc_ref: Mapped[str | None] = mapped_column()

    __table_args__ = (
        UniqueConstraint(
            "legislator_id", "donor_id", "election_year", "donation_type",
            name="uq_donor_link",
        ),
    )

import uuid
from datetime import date
from sqlalchemy import String, Date, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from .base import Base


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    camara_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    type: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)

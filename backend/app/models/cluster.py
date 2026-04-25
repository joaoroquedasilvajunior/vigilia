import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID, ARRAY, JSONB
from .base import Base


class BehavioralCluster(Base):
    __tablename__ = "behavioral_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    dominant_themes: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    member_count: Mapped[int | None] = mapped_column(Integer)
    cohesion_score: Mapped[float | None] = mapped_column(Float)
    algorithm: Mapped[str | None] = mapped_column(String(50))
    algorithm_params: Mapped[dict | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now)

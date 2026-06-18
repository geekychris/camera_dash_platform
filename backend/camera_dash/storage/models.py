"""SQLAlchemy 2.0 ORM models for cameras, pipelines, events, and clips."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(128), default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    @classmethod
    def select_all(cls):
        return select(cls)

    @classmethod
    async def upsert(cls, s: AsyncSession, spec: Any) -> None:
        existing = await s.get(cls, spec.id)
        if existing is None:
            s.add(cls(id=spec.id, kind=spec.kind, label=spec.label,
                     params=spec.params, enabled=spec.enabled))
        else:
            existing.kind = spec.kind
            existing.label = spec.label
            existing.params = spec.params
            existing.enabled = spec.enabled

    @classmethod
    async def delete(cls, s: AsyncSession, camera_id: str) -> None:
        await s.execute(delete(cls).where(cls.id == camera_id))


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)  # graph JSON
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now)

    @classmethod
    def select_all(cls):
        return select(cls)

    @classmethod
    async def upsert(cls, s: AsyncSession, pid: str, name: str,
                     definition: dict[str, Any], enabled: bool) -> Pipeline:
        existing = await s.get(cls, pid)
        if existing is None:
            row = cls(id=pid, name=name, definition=definition, enabled=enabled)
            s.add(row)
            return row
        existing.name = name
        existing.definition = definition
        existing.enabled = enabled
        return existing

    @classmethod
    async def delete(cls, s: AsyncSession, pid: str) -> None:
        await s.execute(delete(cls).where(cls.id == pid))


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str] = mapped_column(String(64), index=True)
    node_id: Mapped[str] = mapped_column(String(64))
    camera_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now,
                                                 index=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # uuid
    camera_id: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_id: Mapped[str | None] = mapped_column(String(64), ForeignKey("pipelines.id",
                                                                            ondelete="SET NULL"),
                                                     nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    path: Mapped[str] = mapped_column(String(512))
    trigger: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

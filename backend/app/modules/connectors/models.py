"""Data sources and the catalog the platform builds from them."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin, new_id


class DataSource(TimestampMixin, Base):
    __tablename__ = "data_sources"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    # projects that may use the source; NULL = every project of the organisation
    project_ids: Mapped[list[uuid.UUID] | None] = mapped_column(ARRAY(UUID(as_uuid=True)))
    status: Mapped[str] = mapped_column(String(16), default="new")  # new | ok | error
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    catalog_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    row_limit: Mapped[int] = mapped_column(Integer, default=10_000)
    max_concurrency: Mapped[int] = mapped_column(Integer, default=4)
    cache_ttl_s: Mapped[int] = mapped_column(Integer, default=900)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    tables: Mapped[list[CatalogTable]] = relationship(back_populates="source", cascade="all, delete-orphan")


class CatalogTable(TimestampMixin, Base):
    __tablename__ = "catalog_tables"
    __table_args__ = (UniqueConstraint("source_id", "schema_name", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"), index=True)
    schema_name: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16), default="table")
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    last_modified: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_comment: Mapped[str] = mapped_column(Text, default="")
    # curated metadata (read by the AI assistant)
    description: Mapped[str] = mapped_column(Text, default="")
    owner: Mapped[str] = mapped_column(String(200), default="")
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)), default=list)
    present: Mapped[bool] = mapped_column(Boolean, default=True)  # still exists in the source

    source: Mapped[DataSource] = relationship(back_populates="tables")
    columns: Mapped[list[CatalogColumn]] = relationship(
        back_populates="table", cascade="all, delete-orphan", order_by="CatalogColumn.ordinal", lazy="selectin"
    )


class CatalogColumn(Base):
    __tablename__ = "catalog_columns"
    __table_args__ = (UniqueConstraint("table_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_id)
    table_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("catalog_tables.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    data_type: Mapped[str] = mapped_column(String(200))
    nullable: Mapped[bool] = mapped_column(Boolean, default=True)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    source_comment: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    is_pii: Mapped[bool] = mapped_column(Boolean, default=False)
    present: Mapped[bool] = mapped_column(Boolean, default=True)

    table: Mapped[CatalogTable] = relationship(back_populates="columns")

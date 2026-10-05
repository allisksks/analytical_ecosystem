"""Shared Pydantic base classes."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class Page[T](Schema):
    items: list[T]
    total: int

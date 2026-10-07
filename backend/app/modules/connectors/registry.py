"""Connector registry: type -> plugin class, plus the roadmap of planned sources (TZ, section 4)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.modules.connectors.base import Connector
from app.modules.connectors.plugins.clickhouse import ClickHouseConnector
from app.modules.connectors.plugins.duckdb_files import FilesConnector, S3Connector
from app.modules.connectors.plugins.gsheets import GoogleSheetsConnector
from app.modules.connectors.plugins.mysql import MySQLConnector
from app.modules.connectors.plugins.postgres import PostgresConnector

PLUGINS: dict[str, type[Connector]] = {
    c.type: c
    for c in (
        ClickHouseConnector,
        PostgresConnector,
        MySQLConnector,
        FilesConnector,
        S3Connector,
        GoogleSheetsConnector,
    )
}


@dataclass(frozen=True)
class Planned:
    type: str
    title: str
    kind: str
    mode: str
    stage: str


PLANNED: tuple[Planned, ...] = (
    Planned("bigquery", "BigQuery", "облачное DWH", "live", "Этап 2"),
    Planned("appmetrica", "AppMetrica (Logs API)", "мобильная аналитика", "sync", "Этап 2"),
    Planned("firebase", "Firebase / GA4 (экспорт в BigQuery)", "мобильная аналитика", "live", "Этап 2"),
    Planned("appsflyer", "AppsFlyer (Pull API, Data Locker)", "атрибуция", "sync", "Этап 2"),
    Planned("applovin", "AppLovin MAX, IronSource", "рекламная монетизация", "sync", "Этап 2"),
    Planned("mssql", "MS SQL Server, Oracle", "реляционная", "live", "Этап 4"),
    Planned("snowflake", "Snowflake, Trino / Presto", "облачное DWH / движок запросов", "live", "Этап 4"),
    Planned("yandex_metrika", "Яндекс Метрика, 1С, amoCRM / Bitrix24", "веб-аналитика / CRM", "sync", "Этап 4"),
    Planned("kafka", "Kafka", "поток событий", "sync", "Этап 4"),
)


def plugin(type_: str) -> type[Connector]:
    cls = PLUGINS.get(type_)
    if cls is None:
        raise ValidationFailed(f"Неизвестный тип источника: {type_}")
    return cls


def split_secrets(type_: str, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    cls = plugin(type_)
    public = {k: v for k, v in config.items() if k not in cls.secret_fields and not k.startswith("_")}
    secrets = {k: v for k, v in config.items() if k in cls.secret_fields and v not in (None, "")}
    return public, secrets


def validate_config(type_: str, config: dict[str, Any]) -> None:
    schema = plugin(type_).config_schema
    missing = [k for k in schema.get("required", []) if config.get(k) in (None, "")]
    if missing:
        raise ValidationFailed("Не заполнены обязательные поля", details={"missing": missing})
    props = schema.get("properties", {})
    unknown = [k for k in config if k not in props]
    if unknown:
        raise ValidationFailed("Неизвестные параметры", details={"unknown": unknown})


def storage_dir_for(source_id: str) -> Path:
    return Path(get_settings().storage_dir).resolve() / "sources" / source_id


def instantiate(type_: str, config: dict[str, Any], secrets: dict[str, Any], source_id: str | None = None) -> Connector:
    cls = plugin(type_)
    cfg = dict(config)
    if source_id:
        cfg["_storage_dir"] = str(storage_dir_for(source_id))
    return cls(cfg, secrets)

"""Post-release validation: compares actual data in the client's source with the approved event schemas.

Checks (TZ 3.3, Must): missing event, volume below 50% of the baseline, wrong parameter type, empty
required parameter. Additionally: stale data and a release regression check (event rate per active
user-day in the newest app version vs the previous one, per platform) — the check that catches
"after 1.8.0 iap_purchase stopped firing on iOS" even when the whole window is already after release.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import sqlglot
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ValidationFailed
from app.modules.connectors.models import DataSource
from app.modules.connectors.service import pool
from app.modules.ems.models import Alert, Event, EventVersion, NotificationChannel, TrackingConfig, ValidationRun
from app.modules.ems.notify import dispatch
from app.modules.ems.service import parse_params, quoted
from app.modules.iam.models import Project
from app.modules.iam.service import system_principal
from app.modules.query import service as query_service

log = structlog.get_logger("ems.validation")
TYPE_OK: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "enum": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "timestamp": lambda v: isinstance(v, (str, int)),
    "json": lambda v: isinstance(v, (dict, list)),
}
MIN_USERS = 100


@dataclass
class Finding:
    kind: str
    severity: str
    event: str
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return f"{self.kind}:{self.event}:{self.details.get('platform', '')}:{self.details.get('param', '')}"


def _version_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return (0,)


class Validator:
    def __init__(self, db: AsyncSession, project: Project, cfg: TrackingConfig, source: DataSource) -> None:
        self.db, self.project, self.cfg, self.source = db, project, cfg, source
        self.principal = system_principal(project.org_id, "ems-validator")
        self.dialect = "duckdb"

    async def q(self, sql: str, limit: int = 10_000) -> list[list[Any]]:
        native = sqlglot.transpile(sql, read="postgres", write=self.dialect)[0]
        out = await query_service.execute(
            self.db, self.principal, self.source, self.project, native, origin="ems", limit=limit, use_cache=False
        )
        return out.rows

    def col(self, name: str) -> str:
        return quoted(self.cfg, name)

    async def run(self) -> tuple[list[Finding], dict[str, Any], list[dict[str, Any]], date | None]:
        self.dialect = (await pool.get(self.source)).dialect
        t, dcol, ncol = self.cfg.table, self.col("date_column"), self.col("name_column")
        rows = await self.q(f"SELECT MAX({dcol}) FROM {t}")
        if not rows or rows[0][0] is None:
            return [Finding("stale_data", "critical", "", "Нет данных о событиях", f"Таблица {t} пуста")], {}, [], None
        d_max = date.fromisoformat(str(rows[0][0])[:10])
        today = datetime.now(UTC).date()
        findings: list[Finding] = []
        if (today - d_max).days > 2:
            findings.append(
                Finding(
                    "stale_data",
                    "critical",
                    "",
                    "Данные о событиях не поступают",
                    f"Последние данные за {d_max.isoformat()}",
                    {"last_date": d_max.isoformat()},
                )
            )
        window = d_max - timedelta(days=1) if d_max >= today else d_max
        start = window - timedelta(days=7)
        counts = await self.q(
            f"SELECT {ncol}, CAST({dcol} AS DATE), COUNT(*) FROM {t} "
            f"WHERE {dcol} >= CAST('{start}' AS DATE) AND {dcol} <= CAST('{window}' AS DATE) GROUP BY 1, 2"
        )
        by_event: dict[str, dict[str, int]] = defaultdict(dict)
        for name, day, n in counts:
            by_event[str(name)][str(day)[:10]] = int(n)

        events = list((await self.db.execute(select(Event).where(Event.project_id == self.project.id))).scalars())
        registered = {e.name: e for e in events}
        approved: dict[str, EventVersion] = {}
        for e in events:
            if e.current_version:
                v = (
                    await self.db.execute(
                        select(EventVersion).where(
                            EventVersion.event_id == e.id, EventVersion.version == e.current_version
                        )
                    )
                ).scalar_one_or_none()
                if v:
                    approved[e.name] = v

        results: dict[str, dict[str, Any]] = {}
        for e in events:
            if e.status not in ("active", "deprecated"):
                continue
            days = by_event.get(e.name, {})
            current = days.get(window.isoformat(), 0)
            base_days = [days.get((window - timedelta(days=i)).isoformat(), 0) for i in range(1, 8)]
            baseline = sum(base_days) / 7
            res: dict[str, Any] = {
                "event": e.name,
                "count": current,
                "baseline": round(baseline, 1),
                "status": "ok",
                "checks": [],
            }
            results[e.name] = res
            if e.status == "deprecated":
                if current > 0:
                    res["checks"].append({"check": "deprecated_firing", "status": "warning", "count": current})
                continue
            if current == 0:
                findings.append(
                    Finding(
                        "missing",
                        "critical",
                        e.name,
                        f"Событие {e.name} не приходит",
                        f"За {window.isoformat()} нет ни одного события (база {baseline:.0f}/день)",
                        {"baseline": baseline, "date": window.isoformat()},
                    )
                )
                res["status"] = "critical"
            elif baseline > 0 and current < self.cfg.drop_threshold * baseline:
                ratio = current / baseline
                sev = "critical" if ratio < 0.2 else "warning"
                findings.append(
                    Finding(
                        "volume_drop",
                        sev,
                        e.name,
                        f"Частота {e.name} упала до {ratio:.0%} от базовой",
                        f"{current} событий за {window.isoformat()} при среднем {baseline:.0f} за 7 дней",
                        {"count": current, "baseline": baseline, "ratio": ratio},
                    )
                )
                res["status"] = sev

        findings += await self._release_regression(d_max, registered, results)
        findings += await self._schema_checks(window, approved, results)
        unknown = sorted(set(by_event) - {n for n, e in registered.items() if e.status != "archived"})
        summary = {
            "data_until": d_max.isoformat(),
            "window": window.isoformat(),
            "events_checked": len(results),
            "unregistered_events": unknown,
            "findings": len(findings),
        }
        return findings, summary, list(results.values()), d_max

    async def _release_regression(
        self, d_max: date, registered: dict[str, Event], results: dict[str, Any]
    ) -> list[Finding]:
        t, dcol, ncol = self.cfg.table, self.col("date_column"), self.col("name_column")
        pcol, vcol, ucol = self.col("platform_column"), self.col("version_column"), self.col("user_column")
        since = d_max - timedelta(days=60)
        user_days = await self.q(
            f"SELECT {pcol}, {vcol}, COUNT(*) FROM (SELECT DISTINCT {pcol}, {vcol}, {ucol}, {dcol} FROM {t} "
            f"WHERE {dcol} >= CAST('{since}' AS DATE)) s GROUP BY 1, 2"
        )
        ud: dict[tuple[str, str], int] = {(str(p), str(v)): int(n) for p, v, n in user_days}
        ev_counts = await self.q(
            f"SELECT {pcol}, {vcol}, {ncol}, COUNT(*) FROM {t} WHERE {dcol} >= CAST('{since}' AS DATE) GROUP BY 1, 2, 3",
            limit=50_000,
        )
        counts: dict[tuple[str, str, str], int] = {(str(p), str(v), str(n)): int(c) for p, v, n, c in ev_counts}
        findings = []
        platforms = {p for p, _ in ud}
        for platform in sorted(platforms):
            versions = sorted((v for p, v in ud if p == platform), key=_version_key)
            if len(versions) < 2:
                continue
            new, prev = versions[-1], versions[-2]
            if ud[(platform, new)] < MIN_USERS or ud[(platform, prev)] < MIN_USERS:
                continue
            for name, ev in registered.items():
                if ev.status != "active":
                    continue
                r_new = counts.get((platform, new, name), 0) / ud[(platform, new)]
                r_prev = counts.get((platform, prev, name), 0) / ud[(platform, prev)]
                if r_prev > 0 and r_new < self.cfg.drop_threshold * r_prev:
                    ratio = r_new / r_prev
                    findings.append(
                        Finding(
                            "release_regression",
                            "critical",
                            name,
                            f"{name}: в релизе {new} на {platform} событие отправляется в {1 / max(ratio, 1e-6):.1f} раза реже",
                            f"На пользователя-день: {r_new:.4f} в {new} против {r_prev:.4f} в {prev} ({ratio:.0%})",
                            {"platform": platform, "version": new, "previous": prev, "ratio": ratio},
                        )
                    )
                    if name in results:
                        results[name]["status"] = "critical"
                        results[name]["checks"].append(
                            {
                                "check": "release_regression",
                                "platform": platform,
                                "version": new,
                                "ratio": round(ratio, 3),
                            }
                        )
        return findings

    async def _schema_checks(
        self, window: date, approved: dict[str, EventVersion], results: dict[str, Any]
    ) -> list[Finding]:
        t, dcol, ncol, pcol = (
            self.cfg.table,
            self.col("date_column"),
            self.col("name_column"),
            self.col("params_column"),
        )
        names = ", ".join("'" + n.replace("'", "''") + "'" for n in approved)
        if not names:
            return []
        sample = await self.q(
            f"SELECT {ncol}, {pcol} FROM {t} WHERE {dcol} = CAST('{window}' AS DATE) AND {ncol} IN ({names})",
            limit=30_000,
        )
        by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for name, raw in sample:
            if len(by_event[str(name)]) < 2000:
                by_event[str(name)].append(parse_params(raw))
        findings = []
        for name, rows in by_event.items():
            v = approved[name]
            n = len(rows)
            for p in v.params:
                missing = sum(1 for r in rows if r.get(p["name"]) in (None, ""))
                if p.get("required") and missing / n > 0.01:
                    findings.append(
                        Finding(
                            "required_empty",
                            "warning",
                            name,
                            f"{name}.{p['name']}: пустой обязательный параметр",
                            f"Не заполнен в {missing / n:.0%} событий ({missing} из {n})",
                            {"param": p["name"], "share": missing / n},
                        )
                    )
                check = TYPE_OK[p["type"]]
                present = [r[p["name"]] for r in rows if r.get(p["name"]) not in (None, "")]
                bad = [x for x in present if not check(x) or (p["type"] == "enum" and str(x) not in p.get("enum", []))]
                if present and len(bad) / len(present) > 0.01:
                    findings.append(
                        Finding(
                            "type_mismatch",
                            "warning",
                            name,
                            f"{name}.{p['name']}: неверный тип или значение",
                            f"Ожидается {p['type']}, не совпадает {len(bad) / len(present):.0%}; пример: {bad[0]!r}",
                            {"param": p["name"], "share": len(bad) / len(present), "example": str(bad[0])[:100]},
                        )
                    )
            if name in results:
                results[name]["sampled"] = n
        return findings


async def run_validation(db: AsyncSession, project: Project, base_url: str = "") -> ValidationRun:
    cfg = await db.get(TrackingConfig, project.id)
    if cfg is None:
        raise ValidationFailed("Для проекта не настроен источник событий (Реестр событий → Настройки)")
    source = await db.get(DataSource, cfg.source_id)
    if source is None:
        raise ValidationFailed("Источник событий удалён")
    run = ValidationRun(project_id=project.id, status="ok")
    db.add(run)
    try:
        findings, summary, results, d_max = await Validator(db, project, cfg, source).run()
    except Exception as exc:  # report the failure as a run, do not crash the scheduler
        log.warning("validation failed", project=project.key, error=str(exc))
        run.status, run.error = "error", str(exc)[:1000]
        await db.commit()
        return run
    run.summary, run.results = summary, results
    run.data_until = datetime(d_max.year, d_max.month, d_max.day, tzinfo=UTC) if d_max else None
    run.status = "critical" if any(f.severity == "critical" for f in findings) else "warning" if findings else "ok"
    await _sync_alerts(db, project, findings, base_url)
    await db.commit()
    return run


async def _sync_alerts(db: AsyncSession, project: Project, findings: list[Finding], base_url: str) -> None:
    now = datetime.now(UTC)
    open_alerts = {
        a.fingerprint: a
        for a in (
            await db.execute(
                select(Alert).where(Alert.project_id == project.id, Alert.status.in_(("open", "acknowledged")))
            )
        ).scalars()
    }
    events = {e.name: e.id for e in (await db.execute(select(Event).where(Event.project_id == project.id))).scalars()}
    channels = list(
        (await db.execute(select(NotificationChannel).where(NotificationChannel.org_id == project.org_id))).scalars()
    )
    seen = set()
    for f in findings:
        seen.add(f.fingerprint)
        existing = open_alerts.get(f.fingerprint)
        if existing:
            existing.last_seen_at, existing.message, existing.severity = now, f.message, f.severity
            existing.details = f.details
            continue
        alert = Alert(
            org_id=project.org_id,
            project_id=project.id,
            event_id=events.get(f.event),
            event_name=f.event,
            kind=f.kind,
            severity=f.severity,
            title=f.title,
            message=f.message,
            details=f.details,
            fingerprint=f.fingerprint,
        )
        db.add(alert)
        await db.flush()
        sent = await dispatch(channels, alert, project.name, base_url or get_settings().public_url)
        alert.details = {**f.details, "notified": sent}
    for fp, a in open_alerts.items():
        if fp not in seen:
            a.status, a.resolved_at = "resolved", now


async def validate_all(db: AsyncSession) -> int:
    """Scheduler entry point: validates every project that has a tracking source configured."""
    n = 0
    for cfg in (await db.execute(select(TrackingConfig))).scalars().all():
        project = await db.get(Project, cfg.project_id)
        if project and not project.archived:
            await run_validation(db, project)
            n += 1
    return n


_ = uuid

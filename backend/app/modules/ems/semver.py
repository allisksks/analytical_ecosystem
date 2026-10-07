"""Version arithmetic for event schemas: diff two parameter lists and choose the semver bump.

* major — a parameter removed, its type changed, or an existing/new parameter became required
  (old clients break);
* minor — an optional parameter added or an enum extended;
* patch — only descriptions changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.errors import ValidationFailed
from app.modules.ems.models import PARAM_TYPES

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass
class ParamChange:
    name: str
    kind: str  # added | removed | changed
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    fields: list[str] = field(default_factory=list)


@dataclass
class Diff:
    changes: list[ParamChange]
    bump: str  # major | minor | patch | none

    def as_dict(self) -> dict[str, Any]:
        return {"bump": self.bump, "changes": [c.__dict__ for c in self.changes]}


def normalize_params(params: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, seen = [], set()
    for p in params:
        name = str(p.get("name", "")).strip()
        if not NAME_RE.match(name):
            raise ValidationFailed(f"Имя параметра «{name}» должно быть в snake_case (a-z, 0-9, _)")
        if name in seen:
            raise ValidationFailed(f"Параметр «{name}» указан дважды")
        seen.add(name)
        ptype = p.get("type", "string")
        if ptype not in PARAM_TYPES:
            raise ValidationFailed(
                f"Неизвестный тип «{ptype}» у параметра {name}", details={"allowed": list(PARAM_TYPES)}
            )
        enum = [str(v) for v in p.get("enum") or []]
        if ptype == "enum" and not enum:
            raise ValidationFailed(f"Для enum-параметра {name} перечислите значения")
        out.append(
            {
                "name": name,
                "type": ptype,
                "required": bool(p.get("required", False)),
                "description": str(p.get("description", "")),
                "enum": enum,
            }
        )
    return out


def diff(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> Diff:
    b = {p["name"]: p for p in before}
    a = {p["name"]: p for p in after}
    changes: list[ParamChange] = []
    bump = 0  # 0 none, 1 patch, 2 minor, 3 major
    for name in sorted(b.keys() - a.keys()):
        changes.append(ParamChange(name, "removed", before=b[name]))
        bump = 3
    for name in sorted(a.keys() - b.keys()):
        changes.append(ParamChange(name, "added", after=a[name]))
        bump = max(bump, 3 if a[name].get("required") else 2)
    for name in sorted(a.keys() & b.keys()):
        fields = [f for f in ("type", "required", "enum", "description") if a[name].get(f) != b[name].get(f)]
        if not fields:
            continue
        changes.append(ParamChange(name, "changed", before=b[name], after=a[name], fields=fields))
        if "type" in fields or ("required" in fields and a[name].get("required")):
            bump = max(bump, 3)
        elif "enum" in fields:
            removed = set(b[name].get("enum") or []) - set(a[name].get("enum") or [])
            bump = max(bump, 3 if removed else 2)
        else:
            bump = max(bump, 1)
    return Diff(changes, ["none", "patch", "minor", "major"][bump])


def parse(version: str) -> tuple[int, int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not m:
        raise ValidationFailed(f"Некорректная версия {version}")
    return int(m[1]), int(m[2]), int(m[3])


def next_version(current: str | None, bump: str) -> str:
    if current is None:
        return "1.0.0"
    major, minor, patch = parse(current)
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"

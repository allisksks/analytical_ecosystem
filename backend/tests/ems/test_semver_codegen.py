from __future__ import annotations

import json

import pytest

from app.core.errors import ValidationFailed
from app.modules.ems import codegen, semver

V1 = [{"name": "level", "type": "int", "required": True}, {"name": "mode", "type": "enum", "enum": ["pve", "pvp"]}]


def norm(p: list[dict]) -> list[dict]:  # type: ignore[type-arg]
    return semver.normalize_params(p)


@pytest.mark.parametrize(
    ("after", "bump"),
    [
        ([*V1, {"name": "stars", "type": "int"}], "minor"),
        ([*V1, {"name": "stars", "type": "int", "required": True}], "major"),
        (V1[:1], "major"),
        ([{**V1[0], "type": "string"}, V1[1]], "major"),
        ([V1[0], {**V1[1], "enum": ["pve", "pvp", "coop"]}], "minor"),
        ([V1[0], {**V1[1], "enum": ["pve"]}], "major"),
        ([{**V1[0], "description": "Номер"}, V1[1]], "patch"),
        (V1, "none"),
    ],
)
def test_bump_rules(after: list[dict], bump: str) -> None:  # type: ignore[type-arg]
    assert semver.diff(norm(V1), norm(after)).bump == bump


def test_next_version_and_validation() -> None:
    assert semver.next_version(None, "minor") == "1.0.0"
    assert semver.next_version("1.2.3", "major") == "2.0.0"
    assert semver.next_version("1.2.3", "minor") == "1.3.0"
    assert semver.next_version("1.2.3", "patch") == "1.2.4"
    with pytest.raises(ValidationFailed):
        norm([{"name": "Bad Name"}])
    with pytest.raises(ValidationFailed):
        norm([{"name": "x", "type": "enum"}])
    with pytest.raises(ValidationFailed):
        norm([{"name": "x"}, {"name": "x"}])


EV = {
    "name": "level_complete",
    "description": "Уровень пройден",
    "version": "1.1.0",
    "project": "iron_shells",
    "params": norm(V1),
}


def test_json_schema_is_valid_draft_2020() -> None:
    schema = codegen.json_schema(EV, EV["params"], [{"name": "user_id", "type": "string", "required": True}])
    assert schema["$schema"].endswith("2020-12/schema")
    assert set(schema["required"]) == {"event_name", "user_id", "level"}
    assert schema["properties"]["mode"]["enum"] == ["pve", "pvp"]
    json.dumps(schema)


@pytest.mark.parametrize("lang", ["typescript", "kotlin", "swift", "csharp"])
def test_codegen_contains_constants_and_params(lang: str) -> None:
    code = codegen.generate(lang, [EV], namespace="IronShells")
    assert "level_complete" in code
    assert ("LevelComplete" in code) or ("LEVEL_COMPLETE" in code)
    assert "level" in code
    assert code.startswith("// Generated")

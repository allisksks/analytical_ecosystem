"""Prompt builders. Pure functions (no DB), so the golden-set exam uses exactly the production prompts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlglot
import yaml

from app.modules.semantic.service import PACKS_DIR

ASK_SYSTEM = """Ты — ассистент аналитической платформы игровой студии. Отвечаешь на вопросы сотрудников \
по внутренней базе знаний: эксперименты, исследования, инциденты, плейбуки, решения, определения метрик.

Правила:
- Отвечай только на основе приведённых источников. Не придумывай факты и цифры.
- Ставь ссылки на источники в квадратных скобках: [1], [2]. Каждый факт — со ссылкой.
- Если в источниках нет ответа, прямо скажи: «В базе знаний об этом нет записей» и подскажи, кого или что спросить.
- Пиши по-русски, кратко и по делу: 2–6 предложений или короткий список.
"""

SQL_SYSTEM = """Ты — опытный аналитик. Пишешь ОДИН читающий SQL-запрос (SELECT или WITH … SELECT) \
на диалекте {dialect} к хранилищу игровой студии.

Правила:
- Используй только таблицы и колонки из схемы ниже. Не выдумывай колонки.
- Относительные периоды («вчера», «за 7 дней») считай от CURRENT_DATE.
- Не фильтруй по app_id и проекту — фильтры доступа платформа добавит сама.
- Давай колонкам понятные псевдонимы на английском (dau, revenue, retention_d1…).
- Никаких INSERT/UPDATE/DELETE/DDL.
- Ответ: SQL в блоке ```sql```, затем одна строка пояснения по-русски.
"""

EXPERIMENT_SYSTEM = """Ты — руководитель аналитики. По итогам A/B-эксперимента пишешь черновик вывода для базы знаний: \
3–5 предложений по-русски. Укажи: подтвердилась ли гипотеза, величину эффекта с интервалом и вероятностью, \
что с защитными метриками и сегментами, есть ли проблемы с качеством данных (SRM), и рекомендацию \
(раскатить / оставить контроль / повторить). Не придумывай чисел — бери только из данных."""

WIDGET_SYSTEM = """Ты — аналитик. По данным виджета дашборда сформулируй 2–4 наблюдения списком по-русски: \
тренды, аномалии, лидеры и аутсайдеры, с конкретными числами из данных. Без общих слов и советов."""


@dataclass
class TableDoc:
    name: str
    columns: list[tuple[str, str, str]]  # (name, type, description)
    description: str = ""


@dataclass
class GoldenPair:
    id: str
    question: str
    sql: str
    tags: list[str] = field(default_factory=list)

    @property
    def tables(self) -> set[str]:
        try:
            return {t.name.lower() for t in sqlglot.parse_one(self.sql, read="postgres").find_all(sqlglot.exp.Table)}
        except sqlglot.errors.ParseError:
            return set()


def load_golden(pack: str = "gaming", path: Path | None = None) -> list[GoldenPair]:
    path = path or PACKS_DIR / pack / "golden_sql.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldenPair(p["id"], p["question"], p["sql"].strip(), p.get("tags", [])) for p in data["pairs"]]


_WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)


def _stems(text: str) -> set[str]:
    """Crude stemming (first 5 letters) — enough to match «выручка/выручку», «установки/установок»."""
    return {w[:5].lower() for w in _WORD.findall(text) if len(w) > 2}


def select_examples(
    question: str, pairs: list[GoldenPair], tables: set[str], k: int = 6, exclude: str | None = None
) -> list[GoldenPair]:
    """Few-shot examples most similar to the question, restricted to tables that exist in the source."""
    q = _stems(question)
    usable = [p for p in pairs if p.id != exclude and p.tables <= tables]
    scored = sorted(usable, key=lambda p: (-len(q & _stems(p.question)) / (len(q | _stems(p.question)) or 1), p.id))
    return scored[:k]


def _transpile(sql: str, dialect: str) -> str:
    if dialect == "postgres":
        return sql
    try:
        return sqlglot.transpile(sql, read="postgres", write=dialect, pretty=False)[0]
    except sqlglot.errors.SqlglotError:
        return sql


def schema_text(tables: list[TableDoc], limit: int = 40) -> str:
    lines = []
    for t in tables[:limit]:
        cols = ", ".join(f"{n} {typ}" + (f" -- {d}" if d else "") for n, typ, d in t.columns[:60])
        lines.append(f"TABLE {t.name}" + (f"  -- {t.description}" if t.description else "") + f"\n  ({cols})")
    return "\n".join(lines)


def sql_messages(
    question: str,
    dialect: str,
    tables: list[TableDoc],
    examples: list[GoldenPair],
    metrics: list[str] | None = None,
) -> list[dict[str, str]]:
    system = SQL_SYSTEM.format(dialect=dialect) + "\nСхема:\n" + schema_text(tables)
    if metrics:
        system += "\n\nОпределения метрик компании:\n" + "\n".join(f"- {m}" for m in metrics[:40])
    msgs = [{"role": "system", "content": system}]
    for ex in examples:
        msgs.append({"role": "user", "content": ex.question})
        msgs.append({"role": "assistant", "content": f"```sql\n{_transpile(ex.sql, dialect)}\n```"})
    msgs.append({"role": "user", "content": question})
    return msgs


SQL_BLOCK = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_sql(text: str) -> tuple[str, str]:
    """(sql, explanation) from a model answer."""
    m = SQL_BLOCK.search(text)
    if m:
        sql = m.group(1).strip()
        explanation = (text[: m.start()] + text[m.end() :]).strip()
    else:
        sql, explanation = text.strip(), ""
    return sql.rstrip(";").strip(), explanation


def repair_message(sql: str, error: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"Запрос отклонён проверкой: {error}\nИсправь запрос и верни его снова в блоке ```sql```.",
    }


def ask_messages(question: str, passages: list[Any]) -> list[dict[str, str]]:
    ctx = "\n\n".join(f"[{i}] {p.title} ({p.type})\n{p.text}" for i, p in enumerate(passages, 1))
    user = f"Источники:\n{ctx or '— нет подходящих записей —'}\n\nВопрос: {question}"
    return [{"role": "system", "content": ASK_SYSTEM}, {"role": "user", "content": user}]


def experiment_messages(design: dict[str, Any], result: dict[str, Any]) -> list[dict[str, str]]:
    payload = json.dumps({"design": design, "result": result}, ensure_ascii=False, default=str)
    return [{"role": "system", "content": EXPERIMENT_SYSTEM}, {"role": "user", "content": payload}]


def widget_messages(title: str, columns: list[str], rows: list[list[Any]]) -> list[dict[str, str]]:
    table = "\n".join([" | ".join(columns), *(" | ".join(str(v) for v in r) for r in rows[:60])])
    return [{"role": "system", "content": WIDGET_SYSTEM}, {"role": "user", "content": f"{title}\n\n{table}"}]


TRACKING_SYSTEM = """Ты — аналитик продукта мобильной игры. Тебе дают документ с описанием новой версии \
(фичи, изменения, эксперименты) и текущий реестр событий аналитики. Предложи разметку: какие события \
нужно завести или изменить, чтобы измерить фичи из документа.

Правила:
- Имена событий в snake_case по схеме объект_действие: shop_open, offer_purchase, quest_complete.
- Сначала ищи подходящее событие в реестре. Если оно есть — предлагай "update" с недостающими параметрами, \
а не новое событие с похожим смыслом.
- Глобальные параметры (они уже есть в каждом событии) в params не включай.
- Типы параметров: string, int, float, bool, enum (тогда перечисли значения в enum), timestamp, json.
- Для каждого события укажи цель (goal) и вопрос, на который оно отвечает (question), и дословную цитату \
из документа (quote), на которой основано предложение.
- Не придумывай фичи, которых нет в документе. Если документ не про продукт — верни пустой список.

Ответ — только JSON без пояснений:
{"summary": "2–3 предложения: что меняется в версии и что предлагается разметить",
 "events": [{"action": "create" | "update", "name": "...", "description": "...", "category": "...",
   "goal": "...", "question": "...", "rationale": "почему это событие нужно",
   "quote": "цитата из документа",
   "params": [{"name": "...", "type": "string", "required": true, "description": "...", "enum": []}]}]}
Для "update" в params перечисли только новые или изменённые параметры."""


def tracking_messages(
    document: str, registry: list[dict[str, Any]], global_params: list[str], app_version: str = ""
) -> list[dict[str, str]]:
    reg = "\n".join(
        f"- {e['name']}: {e.get('description', '')} | params: "
        + (", ".join(f"{p['name']}:{p['type']}" for p in e.get("params", [])) or "—")
        for e in registry[:200]
    )
    user = (
        f"Версия приложения: {app_version or 'не указана'}\n\n"
        f"Глобальные параметры: {', '.join(global_params) or '—'}\n\n"
        f"Текущий реестр событий:\n{reg or '— пусто —'}\n\n"
        f"Документ:\n<<<\n{document}\n>>>"
    )
    return [{"role": "system", "content": TRACKING_SYSTEM}, {"role": "user", "content": user}]


def parse_json_object(text: str) -> dict[str, Any]:
    """The first JSON object in a model answer (tolerates ```json fences and surrounding prose)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("в ответе нет JSON-объекта")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("ожидался JSON-объект")
    return data

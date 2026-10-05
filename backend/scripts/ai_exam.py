"""Runs the golden-set exam of the SQL assistant against the configured model.

    uv run python -m scripts.ai_exam [--data demo-data] [--limit N] [--out ai-exam-report.md]

Uses AI_BASE_URL / AI_API_KEY / AI_SQL_MODEL (or AI_CHAT_MODEL) from the environment, exactly like the API.
Exit code 1 when accuracy is below the threshold (70% by default).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from app.modules.ai import exam, prompts
from app.modules.ai.gateway import AiGateway


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="demo-data", type=Path)
    ap.add_argument("--app", default="iron_shells")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--threshold", type=float, default=0.7)
    ap.add_argument("--out", default="ai-exam-report.md", type=Path)
    args = ap.parse_args()

    gw = AiGateway()
    gw.check()
    model = gw.s.ai_sql_model or gw.s.ai_chat_model
    pairs = prompts.load_golden()
    if args.limit:
        pairs = pairs[: args.limit]

    async def generate(messages: list[dict[str, str]]) -> str:
        return (await gw.chat(messages, model=model, temperature=0)).text

    def progress(item: exam.ExamItem) -> None:
        print(f"{'✅' if item.correct else '❌'} {item.id:40s} {item.latency_ms:7.0f} ms  {item.error}", flush=True)

    con = exam.connect(args.data, args.app)
    report = await exam.run_exam(con, pairs, generate, model=model, threshold=args.threshold, on_item=progress)
    args.out.write_text(report.markdown(), encoding="utf-8")
    args.out.with_suffix(".json").write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"\nAccuracy: {report.correct}/{report.total} = {report.accuracy:.1%} -> {'PASSED' if report.passed else 'FAILED'}"
    )
    print(f"Report: {args.out}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

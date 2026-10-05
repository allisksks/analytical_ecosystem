"""Dump the OpenAPI 3.1 schema to a file (the frontend generates its typed client from it).

    uv run python -m scripts.export_openapi ../frontend/src/shared/api/openapi.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.main import create_app


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")
    print(f"OpenAPI schema written to {out}")


if __name__ == "__main__":
    main()

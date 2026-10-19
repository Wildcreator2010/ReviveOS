"""Export and validate the FastAPI OpenAPI snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from revive_api.config import Config
from revive_api.main import create_app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="schemas/openapi/openapi.json")
    args = parser.parse_args()
    document = create_app(Config.from_env()).openapi()
    Draft202012Validator.check_schema(document)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from .r2_store import R2Store


class JsonStore(Protocol):
    def get_json(self, key: str) -> Any: ...


def validate_public_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RuntimeError("R2 latest summary must be a JSON object")
    meta = value.get("meta")
    rankings = value.get("rankings")
    if not isinstance(meta, dict) or meta.get("status") != "live":
        raise RuntimeError("R2 latest summary is not live data")
    if not meta.get("observed_at") or not isinstance(rankings, dict):
        raise RuntimeError("R2 latest summary is missing required publication fields")
    if not isinstance(rankings.get("live"), list) or not rankings["live"]:
        raise RuntimeError("R2 latest summary has no live ranking")
    return value


def export_latest(output: Path, *, store: JsonStore | None = None) -> dict[str, Any]:
    active_store = store or R2Store.from_env()
    summary = validate_public_summary(active_store.get_json("summary/latest.json"))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Export last-good R2 data into the static dashboard")
    parser.add_argument("--output", type=Path, default=Path("web/data/latest.json"))
    args = parser.parse_args()
    summary = export_latest(args.output)
    print(
        json.dumps(
            {
                "status": "ok",
                "observed_at": summary["meta"]["observed_at"],
                "live_games": len(summary["rankings"]["live"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

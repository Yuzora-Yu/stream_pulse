from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .aggregate import aggregate_snapshot, aggregate_window
from .collector import YouTubeClient
from .normalize import GameNormalizer
from .r2_store import R2Store


ROOT = Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_settings() -> tuple[dict[str, Any], GameNormalizer]:
    settings = load_json(ROOT / "config" / "config.json")
    normalizer = GameNormalizer(
        load_json(ROOT / "config" / "game_master.json"),
        load_json(ROOT / "config" / "aliases.json"),
        load_json(ROOT / "config" / "exclusions.json"),
    )
    return settings, normalizer


def normalize_records(records: list[dict[str, Any]], normalizer: GameNormalizer) -> list[dict[str, Any]]:
    return [normalizer.normalize_record(record) for record in records]


def make_summary(
    snapshots: list[list[dict[str, Any]]], settings: dict[str, Any], *, status: str = "live"
) -> dict[str, Any]:
    current = aggregate_snapshot(snapshots[-1], settings["cutoff"])
    window = aggregate_window(
        snapshots,
        settings["cutoff"],
        interval_minutes=int(settings.get("observation_interval_minutes", 30)),
    )
    unique_streamers = sum(game["unique_streamers"] for game in window["games"])
    viewer_hours = round(sum(game["viewer_hours"] for game in window["games"]), 1)
    review_count = sum(1 for row in snapshots[-1] if row.get("review_status") in {"hold", "conflict"})
    return {
        "meta": {
            "schema_version": 1,
            "status": status,
            "observed_at": current["observed_at"],
            "last_success_at": current["observed_at"],
            "observation_interval_minutes": settings.get("observation_interval_minutes", 30),
            "source": "YouTube Data API",
            "scope": "YouTube Gaming / regionCode=JP / 上位ライブ候補",
            "cutoff": settings["cutoff"],
            "review_queue_count": review_count,
            "methodology_url": "../methodology/",
        },
        "totals": {
            **current["totals"],
            "unique_streamers_24h": unique_streamers,
            "viewer_hours_24h": viewer_hours,
        },
        "rankings": {"live": current["games"], "last_24h": window["games"]},
        "peaks": window["peaks"],
        "timeseries": window["timeseries"],
    }


def collect_and_publish(*, fixture: Path | None = None, output: Path | None = None) -> dict[str, Any]:
    settings, normalizer = load_settings()
    if fixture:
        records = load_json(fixture)
    else:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            raise RuntimeError("YOUTUBE_API_KEY is required")
        records = YouTubeClient(api_key).collect(settings)
    normalized = normalize_records(records, normalizer)

    if output:
        summary = make_summary([normalized], settings, status="fixture" if fixture else "live")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        return summary

    store = R2Store.from_env()
    stamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M")
    raw_key = f"{settings['raw_prefix']}/{stamp}.json.gz"
    store.put_gzip_json(raw_key, normalized)

    keys = store.list_keys(f"{settings['raw_prefix']}/", limit=72)[-48:]
    snapshots = [store.get_json(key) for key in keys]
    if not snapshots or keys[-1] != raw_key:
        snapshots.append(normalized)
    summary = make_summary(snapshots[-48:], settings)

    hourly_key = f"{settings['hourly_prefix']}/{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    store.put_json(hourly_key, summary["timeseries"], cache_control="private, max-age=300")
    # Publish latest only after raw persistence and all aggregation have succeeded.
    store.put_json(f"{settings['public_prefix']}/latest.json", summary)
    for game in summary["rankings"]["live"]:
        game_id = game["game_id"]
        game_summary = {
            "meta": summary["meta"],
            "game": game,
            "last_24h": next(
                (item for item in summary["rankings"]["last_24h"] if item["game_id"] == game_id), None
            ),
        }
        store.put_json(f"{settings['public_prefix']}/games/{game_id}.json", game_summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and publish STREAM PULSE data")
    parser.add_argument("--fixture", type=Path, help="Read raw YouTube-like records instead of calling the API")
    parser.add_argument("--output", type=Path, help="Write summary locally instead of R2")
    args = parser.parse_args()
    summary = collect_and_publish(fixture=args.fixture, output=args.output)
    print(json.dumps({"status": "ok", "observed_at": summary["meta"]["observed_at"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()


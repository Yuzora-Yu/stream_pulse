from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .aggregate import aggregate_snapshot, aggregate_window
from .collector import YouTubeClient
from .normalize import GameNormalizer
from .r2_store import R2Store

ROOT = Path(__file__).resolve().parents[1]
RAW_KEY_TIME = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/(\d{4})\.json\.gz$")


class PublicationGuardError(RuntimeError):
    """Raised before latest.json can be replaced with an unusable ranking."""


class RawKeyStore(Protocol):
    def list_keys(self, prefix: str, *, limit: int = 1000) -> list[str]: ...


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


def collection_diagnostics(records: list[dict[str, Any]], *, sample_limit: int = 100) -> dict[str, Any]:
    """Create a safe, deterministic report for tuning aliases without exposing API credentials."""
    statuses = Counter(str(row.get("review_status") or "missing") for row in records)
    games = Counter(
        str(row["canonical_game_id"])
        for row in records
        if row.get("canonical_game_id") and row.get("review_status") == "auto"
    )
    categories = Counter(str(row.get("category_id") or "missing") for row in records)
    candidates = [row for row in records if row.get("review_status") != "auto"]
    candidates.sort(
        key=lambda row: (
            -int(row.get("concurrent_viewers") or 0),
            str(row.get("raw_title") or ""),
            str(row.get("video_id") or ""),
        )
    )
    samples = [
        {
            "raw_title": row.get("raw_title", ""),
            "channel_title": row.get("channel_title", ""),
            "category_id": row.get("category_id"),
            "concurrent_viewers": row.get("concurrent_viewers"),
            "subscriber_count": row.get("subscriber_count"),
            "review_status": row.get("review_status"),
            "canonical_game_id": row.get("canonical_game_id"),
            "evidence": row.get("evidence", []),
            "excluded_reason": row.get("excluded_reason"),
        }
        for row in candidates[:sample_limit]
    ]
    return {
        "observed_at": max(
            (row["observed_at"] for row in records if row.get("observed_at")),
            default=None,
        ),
        "record_count": len(records),
        "status_counts": dict(sorted(statuses.items())),
        "category_counts": dict(sorted(categories.items())),
        "classified_games": dict(sorted(games.items())),
        "unpublished_samples": samples,
    }


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def make_summary(
    snapshots: list[list[dict[str, Any]]], settings: dict[str, Any], *, status: str = "live"
) -> dict[str, Any]:
    if not snapshots:
        raise PublicationGuardError("No snapshots are available for publication")
    current = aggregate_snapshot(snapshots[-1], settings["cutoff"])
    if not current["games"]:
        raise PublicationGuardError(
            "Current observation produced no publishable games; last-good data was preserved"
        )
    window = aggregate_window(
        snapshots,
        settings["cutoff"],
        interval_minutes=int(settings.get("observation_interval_minutes", 30)),
    )
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
            "observed_streams": current["observed_streams"],
            "eligible_streams": current["eligible_streams"],
            "methodology_url": "../methodology/",
        },
        "totals": {
            **current["totals"],
            "unique_streamers_24h": window["totals"]["unique_streamers"],
            "viewer_hours_24h": window["totals"]["viewer_hours"],
        },
        "rankings": {"live": current["games"], "last_24h": window["games"]},
        "peaks": window["peaks"],
        "timeseries": window["timeseries"],
    }


def recent_raw_keys(
    store: RawKeyStore,
    raw_prefix: str,
    *,
    now: datetime,
    hours: int = 24,
) -> list[str]:
    """List raw snapshot keys inside a real time window without scanning all retention history."""
    now = now.astimezone(UTC)
    cutoff = now - timedelta(hours=hours)
    days = {now.date(), cutoff.date()}
    keys: set[str] = set()
    for day in sorted(days):
        prefix = f"{raw_prefix}/{day.strftime('%Y/%m/%d')}/"
        keys.update(store.list_keys(prefix, limit=96))

    selected: list[tuple[datetime, str]] = []
    for key in keys:
        match = RAW_KEY_TIME.search(key)
        if not match:
            continue
        stamp = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M").replace(tzinfo=UTC)
        if cutoff <= stamp <= now:
            selected.append((stamp, key))
    return [key for _, key in sorted(selected)]


def collect_and_publish(
    *,
    fixture: Path | None = None,
    output: Path | None = None,
    diagnostics_output: Path | None = None,
) -> dict[str, Any]:
    settings, normalizer = load_settings()
    if fixture:
        records = load_json(fixture)
    else:
        api_key = os.environ.get("YOUTUBE_API_KEY")
        if not api_key:
            raise RuntimeError("YOUTUBE_API_KEY is required")
        records = YouTubeClient(api_key).collect(settings)
    normalized = normalize_records(records, normalizer)
    diagnostics = collection_diagnostics(normalized)
    if not fixture:
        diagnostics["discovery"] = {
            "region_code": settings.get("region_code", "JP"),
            "relevance_language": settings.get("relevance_language", "ja"),
            "query": settings.get("search_query"),
            "requested_pages": int(settings.get("search_pages", 2)),
            "page_size": int(settings.get("search_page_size", 50)),
        }
    if diagnostics_output:
        write_json(diagnostics_output, diagnostics)
    if not diagnostics["classified_games"]:
        print(
            json.dumps(
                {**diagnostics, "unpublished_samples": diagnostics["unpublished_samples"][:20]},
                ensure_ascii=False,
            )
        )

    if output:
        summary = make_summary([normalized], settings, status="fixture" if fixture else "probe")
        write_json(output, summary)
        return summary

    store = R2Store.from_env()
    collected_at = datetime.now(UTC)
    stamp = collected_at.strftime("%Y/%m/%d/%H%M")
    raw_key = f"{settings['raw_prefix']}/{stamp}.json.gz"
    store.put_gzip_json(raw_key, normalized)

    review_rows = [row for row in normalized if row.get("review_status") in {"hold", "conflict"}]
    if review_rows:
        store.put_json(
            f"review/{stamp}.json",
            review_rows,
            cache_control="private, max-age=300",
        )

    keys = recent_raw_keys(store, settings["raw_prefix"], now=collected_at)
    snapshots = [store.get_json(key) for key in keys]
    if raw_key not in keys:
        snapshots.append(normalized)
    summary = make_summary(snapshots, settings)

    hourly_key = f"{settings['hourly_prefix']}/{datetime.now(UTC).strftime('%Y-%m-%d')}.json"
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
    parser.add_argument(
        "--fixture",
        type=Path,
        help="Read raw YouTube-like records instead of calling the API",
    )
    parser.add_argument("--output", type=Path, help="Write summary locally instead of R2")
    parser.add_argument(
        "--diagnostics-output",
        type=Path,
        help="Write classification diagnostics even when publication is blocked",
    )
    args = parser.parse_args()
    summary = collect_and_publish(
        fixture=args.fixture,
        output=args.output,
        diagnostics_output=args.diagnostics_output,
    )
    print(json.dumps({"status": "ok", "observed_at": summary["meta"]["observed_at"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()


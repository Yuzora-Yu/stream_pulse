from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dictionary_learning import extract_bracket_candidate, extract_hashtags
from .normalize import normalize_text
from .pipeline import ROOT, load_json, recent_raw_keys
from .r2_store import R2Store

MAX_STREAMS = 5


def _derived_snapshot_id(snapshot: list[dict[str, Any]]) -> str:
    """Return a stable fallback ID for tests and callers without an R2 object key."""
    identity = [
        {
            "observed_at": record.get("observed_at"),
            "video_id": record.get("video_id"),
            "channel_id": record.get("channel_id"),
            "canonical_game_id": record.get("canonical_game_id"),
            "review_status": record.get("review_status"),
        }
        for record in snapshot
    ]
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return f"derived:{digest}"


def _stream_sample(record: dict[str, Any]) -> dict[str, Any]:
    video_id = str(record.get("video_id") or "")
    channel_id = str(record.get("channel_id") or "")
    return {
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
        "title": str(record.get("raw_title") or ""),
        "observed_at": record.get("observed_at"),
        "channel_id": channel_id,
        "channel_title": str(record.get("channel_title") or ""),
        "channel_url": f"https://www.youtube.com/channel/{channel_id}" if channel_id else None,
    }


def _candidate_terms(record: dict[str, Any]) -> list[tuple[str, str]]:
    values = list(extract_hashtags(str(record.get("raw_title") or "")))
    bracket = extract_bracket_candidate(str(record.get("raw_title") or ""))
    if bracket and bracket not in values:
        values.append(bracket)
    return values


def build_observation_bundle(
    snapshots: list[list[dict[str, Any]]],
    *,
    known_aliases: set[str],
    snapshot_ids: list[str] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if snapshot_ids is not None and len(snapshot_ids) != len(snapshots):
        raise ValueError("snapshot_ids must align one-to-one with snapshots")
    resolved_snapshot_ids = snapshot_ids or [_derived_snapshot_id(row) for row in snapshots]
    if len(set(resolved_snapshot_ids)) != len(resolved_snapshot_ids):
        raise ValueError("snapshot_ids must be unique within a bundle")

    game_rows: dict[str, dict[str, Any]] = {}
    alias_rows: dict[str, dict[str, Any]] = {}
    snapshot_counts: dict[str, dict[str, Any]] = {}
    observed_times: list[str] = []

    for snapshot_id, snapshot in zip(resolved_snapshot_ids, snapshots, strict=True):
        snapshot_games: Counter[str] = Counter()
        snapshot_aliases: Counter[str] = Counter()
        snapshot_times: list[str] = []
        for record in snapshot:
            observed_at = str(record.get("observed_at") or "")
            if observed_at:
                observed_times.append(observed_at)
                snapshot_times.append(observed_at)
            video_id = str(record.get("video_id") or "")
            channel_id = str(record.get("channel_id") or "")
            sample = _stream_sample(record)
            game_id = str(record.get("canonical_game_id") or "")
            if record.get("review_status") == "auto" and game_id:
                snapshot_games[game_id] += 1
                entry = game_rows.setdefault(
                    game_id,
                    {
                        "first_seen": observed_at or None,
                        "last_seen": observed_at or None,
                        "observation_count": 0,
                        "video_ids": set(),
                        "latest_streams": {},
                    },
                )
                entry["observation_count"] += 1
                if observed_at:
                    entry["first_seen"] = min(
                        filter(None, [entry.get("first_seen"), observed_at]),
                        default=None,
                    )
                    entry["last_seen"] = max(
                        filter(None, [entry.get("last_seen"), observed_at]),
                        default=None,
                    )
                if video_id:
                    entry["video_ids"].add(video_id)
                    previous = entry["latest_streams"].get(video_id)
                    if previous is None or str(previous.get("observed_at") or "") <= observed_at:
                        entry["latest_streams"][video_id] = sample

            for alias, display in _candidate_terms(record):
                if alias in known_aliases:
                    continue
                snapshot_aliases[alias] += 1
                entry = alias_rows.setdefault(
                    alias,
                    {
                        "display": display,
                        "candidate_game_ids": set(),
                        "first_seen": observed_at or None,
                        "last_seen": observed_at or None,
                        "observation_count": 0,
                        "video_ids": set(),
                        "channel_ids": set(),
                        "latest_streams": {},
                        "status": "candidate",
                    },
                )
                entry["observation_count"] += 1
                if observed_at:
                    entry["first_seen"] = min(
                        filter(None, [entry.get("first_seen"), observed_at]),
                        default=None,
                    )
                    entry["last_seen"] = max(
                        filter(None, [entry.get("last_seen"), observed_at]),
                        default=None,
                    )
                if record.get("review_status") == "auto" and game_id:
                    entry["candidate_game_ids"].add(game_id)
                if channel_id:
                    entry["channel_ids"].add(channel_id)
                if video_id:
                    entry["video_ids"].add(video_id)
                    previous = entry["latest_streams"].get(video_id)
                    if previous is None or str(previous.get("observed_at") or "") <= observed_at:
                        entry["latest_streams"][video_id] = sample

        snapshot_counts[snapshot_id] = {
            "observed_at": max(snapshot_times, default=None),
            "games": dict(sorted(snapshot_games.items())),
            "aliases": dict(sorted(snapshot_aliases.items())),
        }

    games: dict[str, Any] = {}
    for game_id, entry in sorted(game_rows.items()):
        streams = sorted(
            entry["latest_streams"].values(),
            key=lambda row: str(row.get("observed_at") or ""),
            reverse=True,
        )[:MAX_STREAMS]
        games[game_id] = {
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "observation_count": entry["observation_count"],
            "stream_count": len(entry["video_ids"]),
            "latest_streams": streams,
        }

    aliases: dict[str, Any] = {}
    for alias, entry in sorted(alias_rows.items()):
        streams = sorted(
            entry["latest_streams"].values(),
            key=lambda row: str(row.get("observed_at") or ""),
            reverse=True,
        )[:MAX_STREAMS]
        aliases[alias] = {
            "display": entry["display"],
            "candidate_game_ids": sorted(entry["candidate_game_ids"]),
            "first_seen": entry["first_seen"],
            "last_seen": entry["last_seen"],
            "observation_count": entry["observation_count"],
            "stream_count": len(entry["video_ids"]),
            "channel_ids": sorted(entry["channel_ids"]),
            "channel_count": len(entry["channel_ids"]),
            "latest_streams": streams,
            "status": entry["status"],
        }

    window_from = min(observed_times) if observed_times else None
    window_to = max(observed_times) if observed_times else None
    generated = generated_at or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    snapshot_digest = hashlib.sha256(
        "\n".join(sorted(resolved_snapshot_ids)).encode("utf-8")
    ).hexdigest()[:24]
    bundle_id = f"stream_pulse:v2:{snapshot_digest}"
    return {
        "schema_version": 2,
        "source": "stream_pulse",
        "bundle_id": bundle_id,
        "generated_at": generated,
        "window": {
            "from": window_from,
            "to": window_to,
        },
        "snapshot_counts": snapshot_counts,
        "games": games,
        "aliases": aliases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a compact observation bundle for game_catalog")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hours", type=int, default=168)
    args = parser.parse_args()

    settings = load_json(ROOT / "config" / "config.json")
    aliases = load_json(ROOT / "config" / "aliases.json")
    known_aliases = {normalize_text(alias) for values in aliases.values() for alias in values}

    store = R2Store.from_env()
    now = datetime.now(UTC)
    keys = recent_raw_keys(store, settings["raw_prefix"], now=now, hours=args.hours)
    snapshots = [store.get_json(key) for key in keys]
    bundle = build_observation_bundle(
        snapshots,
        known_aliases=known_aliases,
        snapshot_ids=keys,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "ok",
                "snapshots": len(snapshots),
                "games": len(bundle["games"]),
                "aliases": len(bundle["aliases"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

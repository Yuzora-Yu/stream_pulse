from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any


def eligible(record: dict[str, Any], cutoff: dict[str, Any]) -> bool:
    subscribers = record.get("subscriber_count")
    viewers = record.get("concurrent_viewers")
    subscriber_match = subscribers is not None and subscribers >= int(cutoff.get("min_subscribers", 1000))
    viewer_match = viewers is not None and viewers >= int(cutoff.get("min_concurrent_viewers", 30))
    if str(cutoff.get("operator", "OR")).upper() == "AND":
        return subscriber_match and viewer_match
    return subscriber_match or viewer_match


def aggregate_snapshot(
    records: Iterable[dict[str, Any]], cutoff: dict[str, Any]
) -> dict[str, Any]:
    source_rows = list(records)
    rows = [
        row
        for row in source_rows
        if row.get("canonical_game_id")
        and row.get("review_status") == "auto"
        and eligible(row, cutoff)
    ]
    distinct_rows: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        identity = str(row.get("channel_id") or row.get("video_id") or "unknown")
        key = (str(row["canonical_game_id"]), identity)
        current = distinct_rows.get(key)
        if current is None or (
            int(row.get("concurrent_viewers") or 0),
            str(row.get("video_id") or ""),
        ) > (
            int(current.get("concurrent_viewers") or 0),
            str(current.get("video_id") or ""),
        ):
            distinct_rows[key] = row
    rows = list(distinct_rows.values())
    observed_at = max(
        (row["observed_at"] for row in source_rows if row.get("observed_at")),
        default=_now(),
    )
    games: dict[str, dict[str, Any]] = {}
    for row in rows:
        game_id = row["canonical_game_id"]
        game = games.setdefault(
            game_id,
            {
                "game_id": game_id,
                "display_name": row.get("display_name", game_id),
                "channel_ids": set(),
                "live_streams": [],
                "current_viewers": 0,
            },
        )
        game["channel_ids"].add(row.get("channel_id"))
        game["current_viewers"] += int(row.get("concurrent_viewers") or 0)
        if row.get("video_id"):
            game["live_streams"].append(
                {
                    "video_id": row["video_id"],
                    "url": f"https://www.youtube.com/watch?v={row['video_id']}",
                    "title": row.get("raw_title", ""),
                    "channel_title": row.get("channel_title", ""),
                    "current_viewers": int(row.get("concurrent_viewers") or 0),
                }
            )

    public_games = []
    for game in games.values():
        live_streamers = len({value for value in game.pop("channel_ids") if value})
        game["live_streams"].sort(
            key=lambda stream: (
                -int(stream["current_viewers"]),
                str(stream["channel_title"]),
                str(stream["video_id"]),
            )
        )
        game["live_streams"] = game["live_streams"][:5]
        public_games.append(
            {
                **game,
                "live_streamers": live_streamers,
                "viewer_density": round(game["current_viewers"] / live_streamers, 1) if live_streamers else 0,
            }
        )
    public_games.sort(key=lambda item: (-item["live_streamers"], -item["current_viewers"], item["game_id"]))
    unique_channels = {row.get("channel_id") for row in rows if row.get("channel_id")}
    return {
        "observed_at": observed_at,
        "games": public_games,
        "totals": _totals(public_games, unique_streamers=len(unique_channels)),
        "eligible_streams": len(rows),
        "observed_streams": len(source_rows),
    }


def aggregate_window(
    normalized_snapshots: list[list[dict[str, Any]]],
    cutoff: dict[str, Any],
    interval_minutes: int = 30,
) -> dict[str, Any]:
    game_channels: dict[str, set[str]] = defaultdict(set)
    all_channels: set[str] = set()
    viewer_hours: dict[str, float] = defaultdict(float)
    view_counts: dict[str, list[int]] = defaultdict(list)
    display_names: dict[str, str] = {}
    snapshots = [aggregate_snapshot(rows, cutoff) for rows in normalized_snapshots]

    for rows in normalized_snapshots:
        for row in rows:
            if (
                not row.get("canonical_game_id")
                or row.get("review_status") != "auto"
                or not eligible(row, cutoff)
            ):
                continue
            game_id = row["canonical_game_id"]
            display_names[game_id] = row.get("display_name", game_id)
            if row.get("channel_id"):
                game_channels[game_id].add(row["channel_id"])
                all_channels.add(row["channel_id"])
            viewer_hours[game_id] += int(row.get("concurrent_viewers") or 0) * interval_minutes / 60
            if row.get("view_count") is not None:
                view_counts[row.get("video_id") or f"{game_id}:unknown"].append(int(row["view_count"]))

    replay_delta_by_game: dict[str, int] = defaultdict(int)
    for rows in normalized_snapshots:
        for row in rows:
            game_id = row.get("canonical_game_id")
            video_id = row.get("video_id")
            if not game_id or not video_id or video_id not in view_counts:
                continue
            values = view_counts[video_id]
            replay_delta_by_game[game_id] += max(values) - min(values) if len(values) > 1 else 0
            view_counts.pop(video_id, None)

    games: list[dict[str, Any]] = [
        {
            "game_id": game_id,
            "display_name": display_names.get(game_id, game_id),
            "unique_streamers": len(channels),
            "viewer_hours": round(viewer_hours[game_id], 1),
            "view_delta": replay_delta_by_game[game_id],
        }
        for game_id, channels in game_channels.items()
    ]
    games.sort(key=lambda item: (-item["unique_streamers"], -item["viewer_hours"], item["game_id"]))
    timeseries = sorted(
        [
            {
                "at": snapshot["observed_at"],
                "live_streamers": snapshot["totals"]["live_streamers"],
                "current_viewers": snapshot["totals"]["current_viewers"],
                "viewer_density": snapshot["totals"]["viewer_density"],
            }
            for snapshot in snapshots
        ],
        key=lambda row: row["at"],
    )
    return {
        "games": games,
        "timeseries": timeseries,
        "peaks": peak_summary(timeseries),
        "totals": {
            "unique_streamers": len(all_channels),
            "viewer_hours": round(sum(viewer_hours.values()), 1),
            "view_delta": sum(replay_delta_by_game.values()),
        },
    }


def peak_summary(timeseries: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
    def peak(key: str) -> dict[str, Any] | None:
        if not timeseries:
            return None
        item = max(timeseries, key=lambda row: (row.get(key, 0), row.get("at", "")))
        return {"at": item.get("at"), "value": item.get(key, 0)}

    return {
        "live_streamers": peak("live_streamers"),
        "current_viewers": peak("current_viewers"),
        "viewer_density": peak("viewer_density"),
    }


def _totals(games: list[dict[str, Any]], *, unique_streamers: int | None = None) -> dict[str, Any]:
    streamers = (
        unique_streamers
        if unique_streamers is not None
        else sum(item["live_streamers"] for item in games)
    )
    viewers = sum(item["current_viewers"] for item in games)
    return {
        "live_streamers": streamers,
        "current_viewers": viewers,
        "viewer_density": round(viewers / streamers, 1) if streamers else 0,
    }


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


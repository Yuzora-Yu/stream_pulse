from __future__ import annotations

import hashlib
import re
from copy import deepcopy
from typing import Any

from .normalize import normalize_text

SCHEMA_VERSION = 1
GENERIC_HASHTAGS = {
    "game",
    "games",
    "gameplay",
    "gaming",
    "fps",
    "live",
    "livestream",
    "nintendo",
    "pc",
    "playstation",
    "ps4",
    "ps5",
    "rpg",
    "short",
    "shorts",
    "steam",
    "switch",
    "xbox",
    "youtube",
    "ゲーム",
    "ゲーム配信",
    "ゲーム実況",
    "スマホゲーム",
    "ホラーゲーム",
    "ライブ",
    "実況",
    "初見",
    "初見歓迎",
    "初見さん大歓迎",
    "初見大歓迎",
    "毎日配信",
    "ネタ勢",
    "新マップ",
    "参加型",
    "生放送",
    "生配信",
    "縦型配信",
    "新作ゲーム",
    "配信",
}
GENERIC_FRAGMENTS = ("vtuber", "ネタバレ", "切り抜き")
GENERIC_PREFIXES = ("gaming", "live", "shorts", "ゲーム実況", "実況配信", "生配信", "縦型配信")


def empty_dictionary_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "alias_candidates": {},
        "game_candidates": {},
        "learned_aliases": {},
        "learned_games": {},
    }


def validate_dictionary_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION:
        return empty_dictionary_state()
    state = empty_dictionary_state()
    for key in state:
        if key == "schema_version":
            continue
        if isinstance(value.get(key), dict):
            state[key] = deepcopy(value[key])
    return state


def extract_hashtags(text: str) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    for raw in re.findall(r"[#＃]([^\s#＃【】\[\]]{2,60})", text or ""):
        display = raw.strip(".,:;!?。、，：；！？)]}）】」』〉》")
        alias = normalize_text(display)
        if _usable_hashtag(alias):
            results.append((alias, display))
    return list(dict.fromkeys(results))


def extract_bracket_candidate(text: str) -> tuple[str, str] | None:
    for raw in re.findall(r"[【\[]([^【】\[\]]{2,60})[】\]]", text or ""):
        display = raw.strip()
        alias = normalize_text(display)
        if _usable_hashtag(alias):
            return alias, display
    return None


def learned_catalog(state: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    valid = validate_dictionary_state(state)
    master: dict[str, dict[str, Any]] = {}
    aliases: dict[str, list[str]] = {
        str(game_id): [str(alias) for alias in values]
        for game_id, values in valid["learned_aliases"].items()
        if isinstance(values, list)
    }
    for game_id, entry in valid["learned_games"].items():
        if not isinstance(entry, dict) or not entry.get("display_name"):
            continue
        master[str(game_id)] = {
            "display_name": str(entry["display_name"]),
            "status": "learned",
        }
        values = entry.get("aliases", [])
        if isinstance(values, list):
            aliases.setdefault(str(game_id), []).extend(str(alias) for alias in values)
    return master, aliases


def update_dictionary_state(
    state: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    known_aliases: set[str],
    alias_min_channels: int = 3,
    game_min_channels: int = 5,
    candidate_limit: int = 2000,
    promote_game_candidates: bool = True,
) -> dict[str, Any]:
    updated = validate_dictionary_state(state)
    alias_candidates = updated["alias_candidates"]
    game_candidates = updated["game_candidates"]

    for record in records:
        channel_id = str(record.get("channel_id") or "")
        observed_at = str(record.get("observed_at") or "")
        if not channel_id:
            continue
        hashtags = extract_hashtags(str(record.get("raw_title") or ""))
        if record.get("review_status") == "auto" and record.get("canonical_game_id"):
            game_id = str(record["canonical_game_id"])
            for alias, display in hashtags:
                if alias in known_aliases:
                    continue
                entry = alias_candidates.setdefault(
                    alias,
                    {
                        "display": display,
                        "games": {},
                        "first_seen": observed_at,
                        "last_seen": observed_at,
                    },
                )
                entry["last_seen"] = max(str(entry.get("last_seen") or ""), observed_at)
                channels = entry.setdefault("games", {}).setdefault(game_id, [])
                _add_unique(channels, channel_id, limit=20)
        elif record.get("review_status") in {"hold", "conflict"}:
            candidates = list(hashtags)
            bracket_candidate = extract_bracket_candidate(str(record.get("raw_title") or ""))
            metadata_aliases = {alias for alias, _ in extract_hashtags(str(record.get("description") or ""))}
            for tag in record.get("tags") or []:
                normalized_tag = normalize_text(str(tag))
                if _usable_hashtag(normalized_tag):
                    metadata_aliases.add(normalized_tag)
            if bracket_candidate and bracket_candidate not in candidates:
                candidates.append(bracket_candidate)
            for alias, display in candidates:
                if alias in known_aliases:
                    continue
                entry = game_candidates.setdefault(
                    alias,
                    {
                        "display": display,
                        "channel_ids": [],
                        "confirmed_channel_ids": [],
                        "sample_titles": [],
                        "first_seen": observed_at,
                        "last_seen": observed_at,
                    },
                )
                entry["last_seen"] = max(str(entry.get("last_seen") or ""), observed_at)
                _add_unique(entry["channel_ids"], channel_id, limit=20)
                if bracket_candidate and alias == bracket_candidate[0] and alias in metadata_aliases:
                    _add_unique(entry["confirmed_channel_ids"], channel_id, limit=20)
                _add_unique(entry["sample_titles"], str(record.get("raw_title") or ""), limit=3)

    for alias, entry in list(alias_candidates.items()):
        games = entry.get("games", {})
        if not isinstance(games, dict) or len(games) != 1:
            continue
        game_id, channels = next(iter(games.items()))
        if isinstance(channels, list) and len(channels) >= alias_min_channels:
            learned = updated["learned_aliases"].setdefault(game_id, [])
            _add_unique(learned, alias, limit=100)

    for alias, entry in list(game_candidates.items()):
        if not promote_game_candidates:
            continue
        channels = entry.get("channel_ids", [])
        confirmed_channels = entry.get("confirmed_channel_ids", [])
        enough_channels = isinstance(channels, list) and len(channels) >= game_min_channels
        metadata_confirmed = isinstance(confirmed_channels, list) and bool(confirmed_channels)
        if not enough_channels and not metadata_confirmed:
            continue
        game_id = _learned_game_id(alias)
        updated["learned_games"].setdefault(
            game_id,
            {
                "display_name": entry.get("display") or alias,
                "aliases": [alias],
                "source": "multi_channel_title_hashtag",
                "channel_count": len(channels),
                "metadata_confirmed": metadata_confirmed,
                "first_seen": entry.get("first_seen"),
                "promoted_at": entry.get("last_seen"),
            },
        )

    updated["alias_candidates"] = _newest(alias_candidates, candidate_limit)
    updated["game_candidates"] = _newest(game_candidates, candidate_limit)
    return updated


def dictionary_diagnostics(state: dict[str, Any]) -> dict[str, int]:
    valid = validate_dictionary_state(state)
    return {
        "learned_games": len(valid["learned_games"]),
        "learned_aliases": sum(len(values) for values in valid["learned_aliases"].values()),
        "game_candidates": len(valid["game_candidates"]),
        "alias_candidates": len(valid["alias_candidates"]),
    }


def _usable_hashtag(alias: str) -> bool:
    if not 2 <= len(alias) <= 60 or alias in GENERIC_HASHTAGS:
        return False
    if any(fragment in alias for fragment in GENERIC_FRAGMENTS):
        return False
    if alias.startswith(GENERIC_PREFIXES):
        return False
    if alias.isdigit() or alias.startswith(("http:", "https:", "www.")):
        return False
    return any(character.isalpha() for character in alias)


def _learned_game_id(alias: str) -> str:
    digest = hashlib.sha256(alias.encode("utf-8")).hexdigest()[:12]
    return f"learned-{digest}"


def _add_unique(values: list[str], value: str, *, limit: int) -> None:
    if value and value not in values:
        values.append(value)
        del values[limit:]


def _newest(values: dict[str, Any], limit: int) -> dict[str, Any]:
    ordered = sorted(
        values.items(),
        key=lambda item: (str(item[1].get("last_seen") or ""), item[0]),
        reverse=True,
    )
    return dict(ordered[: max(1, limit)])

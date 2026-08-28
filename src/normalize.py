from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = re.sub(r"[\s\u3000]+", " ", value)
    return value.strip()


@dataclass(frozen=True)
class Classification:
    canonical_game_id: str | None
    display_name: str
    confidence: float
    evidence: list[str]
    review_status: str
    excluded_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_game_id": self.canonical_game_id,
            "display_name": self.display_name,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "review_status": self.review_status,
            "excluded_reason": self.excluded_reason,
        }


class GameNormalizer:
    def __init__(
        self,
        game_master: dict[str, dict[str, Any]],
        aliases: dict[str, list[str]],
        exclusions: dict[str, list[str]],
    ) -> None:
        self.game_master = game_master
        self.aliases = {
            game_id: sorted({normalize_text(alias) for alias in values}, key=len, reverse=True)
            for game_id, values in aliases.items()
        }
        self.title_exclusions = [normalize_text(x) for x in exclusions.get("title_terms", [])]
        self.description_exclusions = [normalize_text(x) for x in exclusions.get("description_terms", [])]
        self.excluded_channels = set(exclusions.get("channel_ids", []))

    def classify(self, record: dict[str, Any]) -> Classification:
        if record.get("source_excluded_reason"):
            return self._excluded(str(record["source_excluded_reason"]))
        title = normalize_text(record.get("raw_title", ""))
        description = normalize_text(record.get("description", ""))
        if record.get("channel_id") in self.excluded_channels:
            return self._excluded("excluded_channel")
        for term in self.title_exclusions:
            if term and term in title:
                return self._excluded(f"title:{term}")
        for term in self.description_exclusions:
            if term and term in description:
                return self._excluded(f"description:{term}")

        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}
        for game_id, aliases in self.aliases.items():
            for alias in aliases:
                if alias and alias in title:
                    scores[game_id] = max(scores.get(game_id, 0), 0.98 if title == alias else 0.9)
                    evidence.setdefault(game_id, []).append(f"title:{alias}")
                elif alias and alias in description:
                    scores[game_id] = max(scores.get(game_id, 0), 0.62)
                    evidence.setdefault(game_id, []).append(f"description:{alias}")

        if not scores:
            return Classification(None, "未分類", 0.0, [], "hold")
        ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        game_id, score = ordered[0]
        tied = len(ordered) > 1 and ordered[1][1] >= score - 0.05
        status = "conflict" if tied else ("auto" if score >= 0.8 else "hold")
        if tied:
            return Classification(None, "要確認", round(score, 2), evidence[game_id], status)
        display = self.game_master.get(game_id, {}).get("display_name", game_id)
        return Classification(game_id, display, round(score, 2), evidence[game_id], status)

    @staticmethod
    def _excluded(reason: str) -> Classification:
        return Classification(None, "除外", 1.0, [reason], "excluded", reason)

    def normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        classification = self.classify(record)
        return {**record, **classification.as_dict()}


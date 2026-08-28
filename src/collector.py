from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


class YouTubeApiError(RuntimeError):
    """Raised when YouTube returns an unusable response."""


def _chunks(values: list[str], size: int = 50) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


@dataclass(frozen=True)
class YouTubeClient:
    api_key: str
    timeout_seconds: int = 25

    def _get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urlencode({**params, "key": self.api_key})
        request = Request(
            f"{YOUTUBE_API_BASE}/{endpoint}?{query}",
            headers={"Accept": "application/json", "User-Agent": "YU-ZORA-Stream-Pulse/0.1"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # urllib exposes several transport exception types.
            raise YouTubeApiError(f"YouTube API request failed: {endpoint}: {exc}") from exc
        if "error" in payload:
            message = payload["error"].get("message", "unknown API error")
            raise YouTubeApiError(f"YouTube API error: {message}")
        return payload

    def discover_live_video_ids(
        self,
        *,
        region_code: str = "JP",
        relevance_language: str = "ja",
        query: str | None = None,
        pages: int = 2,
        page_size: int = 50,
    ) -> list[str]:
        ids: list[str] = []
        token: str | None = None
        for _ in range(max(1, pages)):
            params: dict[str, Any] = {
                "part": "snippet",
                "type": "video",
                "eventType": "live",
                "order": "viewCount",
                "regionCode": region_code,
                "relevanceLanguage": relevance_language,
                "maxResults": min(50, max(1, page_size)),
            }
            if query:
                params["q"] = query
            if token:
                params["pageToken"] = token
            payload = self._get("search", params)
            ids.extend(
                item.get("id", {}).get("videoId", "")
                for item in payload.get("items", [])
                if item.get("id", {}).get("videoId")
            )
            token = payload.get("nextPageToken")
            if not token:
                break
        return list(dict.fromkeys(ids))

    def fetch_live_details(self, video_ids: list[str]) -> list[dict[str, Any]]:
        videos: list[dict[str, Any]] = []
        for batch in _chunks(video_ids):
            payload = self._get(
                "videos",
                {
                    "part": "snippet,liveStreamingDetails,statistics",
                    "id": ",".join(batch),
                    "maxResults": 50,
                },
            )
            videos.extend(payload.get("items", []))

        channel_ids = list(
            dict.fromkeys(
                video.get("snippet", {}).get("channelId", "")
                for video in videos
                if video.get("snippet", {}).get("channelId")
            )
        )
        channels: dict[str, dict[str, Any]] = {}
        for batch in _chunks(channel_ids):
            payload = self._get(
                "channels",
                {"part": "snippet,statistics", "id": ",".join(batch), "maxResults": 50},
            )
            channels.update({item["id"]: item for item in payload.get("items", [])})

        observed_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        records: list[dict[str, Any]] = []
        for video in videos:
            snippet = video.get("snippet", {})
            live = video.get("liveStreamingDetails", {})
            stats = video.get("statistics", {})
            channel = channels.get(snippet.get("channelId", ""), {})
            channel_stats = channel.get("statistics", {})
            hidden = bool(channel_stats.get("hiddenSubscriberCount", False))
            subscribers = None if hidden else _int_or_none(channel_stats.get("subscriberCount"))
            records.append(
                {
                    "observed_at": observed_at,
                    "video_id": video.get("id"),
                    "channel_id": snippet.get("channelId"),
                    "channel_title": snippet.get("channelTitle", ""),
                    "category_id": snippet.get("categoryId"),
                    "raw_title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "published_at": snippet.get("publishedAt"),
                    "actual_start_time": live.get("actualStartTime"),
                    "scheduled_start_time": live.get("scheduledStartTime"),
                    "concurrent_viewers": _int_or_none(live.get("concurrentViewers")),
                    "view_count": _int_or_none(stats.get("viewCount")),
                    "subscriber_count": subscribers,
                    "hidden_subscriber_count": hidden,
                }
            )
        return records

    def collect(self, settings: dict[str, Any]) -> list[dict[str, Any]]:
        ids = self.discover_live_video_ids(
            region_code=settings.get("region_code", "JP"),
            relevance_language=settings.get("relevance_language", "ja"),
            query=settings.get("search_query"),
            pages=int(settings.get("search_pages", 2)),
            page_size=int(settings.get("search_page_size", 50)),
        )
        records = self.fetch_live_details(ids)
        expected_category = str(settings.get("video_category_id", "")).strip()
        if expected_category:
            for record in records:
                if str(record.get("category_id") or "") != expected_category:
                    record["source_excluded_reason"] = (
                        f"video_category:{record.get('category_id') or 'missing'}"
                    )
        return records


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


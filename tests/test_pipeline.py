import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from src.aggregate import aggregate_snapshot, aggregate_window, eligible
from src.normalize import GameNormalizer, normalize_text
from src.pipeline import PublicationGuardError, make_summary, recent_raw_keys
from src.r2_store import R2Store

ROOT = Path(__file__).resolve().parents[1]


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


class NormalizationTests(unittest.TestCase):
    def setUp(self):
        self.normalizer = GameNormalizer(
            read_json("config/game_master.json"),
            read_json("config/aliases.json"),
            read_json("config/exclusions.json"),
        )

    def test_nfkc_and_case(self):
        self.assertEqual(normalize_text("  ＶＡＬＯＲＡＮＴ　LIVE "), "valorant live")

    def test_alias_classification(self):
        result = self.normalizer.classify(
            {"raw_title": "【初見】モンハンワイルズ", "description": "", "channel_id": "x"}
        )
        self.assertEqual(result.canonical_game_id, "monster-hunter-wilds")
        self.assertEqual(result.review_status, "auto")

    def test_exclusion_wins(self):
        result = self.normalizer.classify(
            {"raw_title": "雑談しながらマイクラ", "description": "", "channel_id": "x"}
        )
        self.assertEqual(result.review_status, "excluded")


class AggregationTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = {"min_subscribers": 1000, "min_concurrent_viewers": 30, "operator": "OR"}
        normalizer = GameNormalizer(
            read_json("config/game_master.json"),
            read_json("config/aliases.json"),
            read_json("config/exclusions.json"),
        )
        self.rows = [normalizer.normalize_record(row) for row in read_json("tests/fixtures/raw_records.json")]

    def test_hidden_subscribers_are_not_zero(self):
        record = {"subscriber_count": None, "concurrent_viewers": 42}
        self.assertTrue(eligible(record, self.cutoff))

    def test_channel_game_is_the_streamer_unit(self):
        snapshot = aggregate_snapshot(self.rows, self.cutoff)
        games = {game["game_id"]: game for game in snapshot["games"]}
        self.assertEqual(games["minecraft"]["live_streamers"], 1)
        self.assertEqual(games["valorant"]["live_streamers"], 1)
        self.assertNotIn("除外", [game["display_name"] for game in snapshot["games"]])

    def test_viewer_hours_use_observation_interval(self):
        window = aggregate_window([self.rows, self.rows], self.cutoff, interval_minutes=30)
        games = {game["game_id"]: game for game in window["games"]}
        self.assertEqual(games["minecraft"]["viewer_hours"], 120.0)
        self.assertEqual(games["minecraft"]["unique_streamers"], 1)

    def test_global_streamer_total_deduplicates_channel_across_games(self):
        rows = [
            {
                "observed_at": "2026-08-28T09:00:00Z",
                "video_id": "a",
                "channel_id": "same-channel",
                "canonical_game_id": "minecraft",
                "display_name": "Minecraft",
                "review_status": "auto",
                "subscriber_count": 5000,
                "concurrent_viewers": 100,
            },
            {
                "observed_at": "2026-08-28T09:00:00Z",
                "video_id": "b",
                "channel_id": "same-channel",
                "canonical_game_id": "valorant",
                "display_name": "VALORANT",
                "review_status": "auto",
                "subscriber_count": 5000,
                "concurrent_viewers": 50,
            },
        ]
        snapshot = aggregate_snapshot(rows, self.cutoff)
        window = aggregate_window([rows], self.cutoff)
        self.assertEqual(snapshot["totals"]["live_streamers"], 1)
        self.assertEqual(window["totals"]["unique_streamers"], 1)

    def test_empty_public_ranking_is_blocked(self):
        settings = read_json("config/config.json")
        held = [[{"observed_at": "2026-08-28T09:00:00Z", "review_status": "hold"}]]
        with self.assertRaises(PublicationGuardError):
            make_summary(held, settings)


class StorageWindowTests(unittest.TestCase):
    def test_recent_keys_are_filtered_to_true_24_hour_window(self):
        class FakeStore:
            def list_keys(self, prefix, *, limit=1000):
                del prefix, limit
                return [
                    "raw/2026/08/27/1159.json.gz",
                    "raw/2026/08/27/1200.json.gz",
                    "raw/2026/08/28/1130.json.gz",
                    "raw/2026/08/28/1230.json.gz",
                    "raw/not-a-snapshot.json.gz",
                ]

        now = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
        self.assertEqual(
            recent_raw_keys(FakeStore(), "raw", now=now),
            ["raw/2026/08/27/1200.json.gz", "raw/2026/08/28/1130.json.gz"],
        )

    def test_r2_listing_consumes_all_pages_before_taking_latest(self):
        class FakePaginator:
            def paginate(self, **kwargs):
                self.kwargs = kwargs
                return [
                    {"Contents": [{"Key": "raw/001"}, {"Key": "raw/002"}]},
                    {"Contents": [{"Key": "raw/003"}, {"Key": "raw/004"}]},
                ]

        class FakeClient:
            def get_paginator(self, name):
                self.name = name
                return FakePaginator()

        class FakeR2Store(R2Store):
            @property
            def client(self):
                return FakeClient()

        store = FakeR2Store("bucket", "account", "key", "secret")
        self.assertEqual(store.list_keys("raw/", limit=2), ["raw/003", "raw/004"])


if __name__ == "__main__":
    unittest.main()


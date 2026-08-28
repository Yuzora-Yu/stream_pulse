import json
import unittest
from pathlib import Path

from src.aggregate import aggregate_snapshot, aggregate_window, eligible
from src.normalize import GameNormalizer, normalize_text


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
        result = self.normalizer.classify({"raw_title": "【初見】モンハンワイルズ", "description": "", "channel_id": "x"})
        self.assertEqual(result.canonical_game_id, "monster-hunter-wilds")
        self.assertEqual(result.review_status, "auto")

    def test_exclusion_wins(self):
        result = self.normalizer.classify({"raw_title": "雑談しながらマイクラ", "description": "", "channel_id": "x"})
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


if __name__ == "__main__":
    unittest.main()


import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.aggregate import aggregate_snapshot, aggregate_window, eligible
from src.collector import YouTubeClient
from src.dictionary_learning import (
    dictionary_diagnostics,
    empty_dictionary_state,
    extract_bracket_candidate,
    extract_hashtags,
    learned_catalog,
    update_dictionary_state,
)
from src.export_latest import export_latest, validate_public_summary
from src.normalize import GameNormalizer, contains_alias, normalize_text
from src.pipeline import (
    PublicationGuardError,
    collection_diagnostics,
    make_summary,
    recent_raw_keys,
    scheduled_slot,
)
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

    def test_short_latin_alias_requires_token_boundaries(self):
        self.assertTrue(contains_alias("league of legends / lol", "lol"))
        self.assertFalse(contains_alias("a lollipop game", "lol"))

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

    def test_source_category_exclusion_wins(self):
        result = self.normalizer.classify(
            {
                "raw_title": "Minecraft live",
                "description": "",
                "channel_id": "x",
                "source_excluded_reason": "video_category:24",
            }
        )
        self.assertEqual(result.review_status, "excluded")
        self.assertEqual(result.excluded_reason, "video_category:24")

    def test_additional_japanese_game_alias(self):
        result = self.normalizer.classify(
            {"raw_title": "【原神】螺旋に挑戦", "description": "", "channel_id": "x"}
        )
        self.assertEqual(result.canonical_game_id, "genshin-impact")
        self.assertEqual(result.review_status, "auto")

    def test_observed_game_aliases(self):
        cases = {
            "GTA 5 LIVE #gaming": "grand-theft-auto-v",
            "【DBD】ライブ配信": "dead-by-daylight",
            "【ブルアカ】100回記念": "blue-archive",
            "【#鳴潮 /初見実況】メインストーリー": "wuthering-waves",
            "【奇天烈相談ダイヤル】敏腕相談員の日常【塩】": "kiteretsu-sodan-dial",
            "Hades II 初見プレイ": "hades-ii",
        }
        for title, game_id in cases.items():
            with self.subTest(title=title):
                result = self.normalizer.classify(
                    {"raw_title": title, "description": "", "channel_id": "x"}
                )
                self.assertEqual(result.canonical_game_id, game_id)
                self.assertEqual(result.review_status, "auto")

    def test_catalog_and_aliases_stay_in_sync(self):
        master = read_json("config/game_master.json")
        aliases = read_json("config/aliases.json")
        self.assertEqual(set(master), set(aliases))
        self.assertGreaterEqual(len(master), 150)
        self.assertGreaterEqual(sum(len(values) for values in aliases.values()), 450)

    def test_collection_diagnostics_prioritizes_high_viewer_unknowns(self):
        diagnostics = collection_diagnostics(
            [
                {
                    "observed_at": "2026-08-28T12:00:00Z",
                    "raw_title": "unknown low",
                    "review_status": "hold",
                    "concurrent_viewers": 10,
                },
                {
                    "observed_at": "2026-08-28T12:00:00Z",
                    "raw_title": "unknown high",
                    "review_status": "hold",
                    "concurrent_viewers": 1000,
                },
            ]
        )
        self.assertEqual(diagnostics["status_counts"], {"hold": 2})
        self.assertEqual(diagnostics["category_counts"], {"missing": 2})
        self.assertEqual(diagnostics["unpublished_samples"][0]["raw_title"], "unknown high")


class CollectorTests(unittest.TestCase):
    def test_search_uses_supported_part_and_category_is_verified_after_fetch(self):
        requests = []

        class FakeYouTubeClient(YouTubeClient):
            def _get(self, endpoint, params):
                requests.append((endpoint, params))
                if endpoint == "search":
                    return {
                        "items": [
                            {"id": {"videoId": "gaming"}},
                            {"id": {"videoId": "music"}},
                        ]
                    }
                if endpoint == "videos":
                    return {
                        "items": [
                            {
                                "id": "gaming",
                                "snippet": {
                                    "channelId": "channel-1",
                                    "channelTitle": "Gamer",
                                    "title": "Minecraft live",
                                    "categoryId": "20",
                                },
                                "liveStreamingDetails": {"concurrentViewers": "100"},
                                "statistics": {},
                            },
                            {
                                "id": "music",
                                "snippet": {
                                    "channelId": "channel-2",
                                    "channelTitle": "Musician",
                                    "title": "Music live",
                                    "categoryId": "10",
                                },
                                "liveStreamingDetails": {"concurrentViewers": "200"},
                                "statistics": {},
                            },
                        ]
                    }
                if endpoint == "channels":
                    return {"items": []}
                raise AssertionError(endpoint)

        client = FakeYouTubeClient("test-key")
        records = client.collect(
            {
                "region_code": "JP",
                "relevance_language": "ja",
                "video_category_id": "20",
                "search_queries": ["ゲーム実況|ゲーム配信", "奇天烈相談ダイヤル"],
                "search_pages": 2,
                "search_page_size": 50,
            }
        )

        search_params = requests[0][1]
        self.assertEqual(search_params["part"], "snippet")
        self.assertEqual(search_params["q"], "ゲーム実況|ゲーム配信")
        self.assertNotIn("videoCategoryId", search_params)
        search_requests = [params for endpoint, params in requests if endpoint == "search"]
        self.assertEqual(len(search_requests), 2)
        self.assertEqual(search_requests[1]["q"], "奇天烈相談ダイヤル")
        self.assertNotIn("source_excluded_reason", records[0])
        self.assertEqual(records[1]["source_excluded_reason"], "video_category:10")


class DictionaryLearningTests(unittest.TestCase):
    def test_extracts_useful_hashtags_and_rejects_generic_tags(self):
        self.assertEqual(
            extract_hashtags(
                "【配信】Apex #エペ部 #ゲーム実況 #ゲーム配信 #初見さん大歓迎 "
                "#新人VTuber #shortslive #steam #5【エーペックスレジェンズ】"
            ),
            [("エペ部", "エペ部")],
        )
        self.assertEqual(
            extract_bracket_candidate("【初見】遊びます【奇天烈相談ダイヤル】"),
            ("奇天烈相談ダイヤル", "奇天烈相談ダイヤル"),
        )

    def test_learns_alias_after_three_distinct_channels(self):
        records = [
            {
                "observed_at": "2026-08-28T14:00:00Z",
                "channel_id": f"channel-{index}",
                "raw_title": "Apex Legends #エペ部",
                "canonical_game_id": "apex-legends",
                "review_status": "auto",
            }
            for index in range(3)
        ]
        state = update_dictionary_state(
            empty_dictionary_state(),
            records,
            known_aliases={"apex legends", "apex"},
        )
        self.assertEqual(state["learned_aliases"], {"apex-legends": ["エペ部"]})
        self.assertEqual(dictionary_diagnostics(state)["learned_aliases"], 1)

    def test_learns_new_game_after_five_distinct_channels(self):
        records = [
            {
                "observed_at": "2026-08-28T14:00:00Z",
                "channel_id": f"channel-{index}",
                "raw_title": "新作を遊ぶ #雪葬",
                "canonical_game_id": None,
                "review_status": "hold",
            }
            for index in range(5)
        ]
        state = update_dictionary_state(
            empty_dictionary_state(),
            records,
            known_aliases=set(),
        )
        master, aliases = learned_catalog(state)
        self.assertEqual(len(master), 1)
        game_id = next(iter(master))
        self.assertEqual(master[game_id]["display_name"], "雪葬")
        self.assertEqual(aliases[game_id], ["雪葬"])

    def test_one_stream_can_learn_game_when_title_and_metadata_agree(self):
        state = update_dictionary_state(
            empty_dictionary_state(),
            [
                {
                    "observed_at": "2026-08-29T00:00:00Z",
                    "channel_id": "indie-channel",
                    "raw_title": "【奇天烈相談ダイヤル】敏腕相談員の日常【塩】",
                    "description": "#ゲーム実況 #奇天烈相談ダイヤル #塩",
                    "tags": [],
                    "canonical_game_id": None,
                    "review_status": "hold",
                }
            ],
            known_aliases=set(),
        )
        master, aliases = learned_catalog(state)
        self.assertEqual(len(master), 1)
        game_id = next(iter(master))
        self.assertEqual(master[game_id]["display_name"], "奇天烈相談ダイヤル")
        self.assertEqual(aliases[game_id], ["奇天烈相談ダイヤル"])


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

    def test_same_channel_game_uses_top_stream_and_exposes_youtube_link(self):
        rows = [
            {
                "observed_at": "2026-08-28T14:00:00Z",
                "video_id": "lower",
                "channel_id": "same-channel",
                "channel_title": "Streamer",
                "raw_title": "Minecraft lower",
                "canonical_game_id": "minecraft",
                "display_name": "Minecraft",
                "review_status": "auto",
                "subscriber_count": 5000,
                "concurrent_viewers": 20,
            },
            {
                "observed_at": "2026-08-28T14:00:00Z",
                "video_id": "higher",
                "channel_id": "same-channel",
                "channel_title": "Streamer",
                "raw_title": "Minecraft higher",
                "canonical_game_id": "minecraft",
                "display_name": "Minecraft",
                "review_status": "auto",
                "subscriber_count": 5000,
                "concurrent_viewers": 100,
            },
        ]
        game = aggregate_snapshot(rows, self.cutoff)["games"][0]
        self.assertEqual(game["live_streamers"], 1)
        self.assertEqual(game["current_viewers"], 100)
        self.assertEqual(game["live_streams"][0]["video_id"], "higher")
        self.assertEqual(
            game["live_streams"][0]["url"],
            "https://www.youtube.com/watch?v=higher",
        )

    def test_empty_public_ranking_is_blocked(self):
        settings = read_json("config/config.json")
        held = [[{"observed_at": "2026-08-28T09:00:00Z", "review_status": "hold"}]]
        with self.assertRaises(PublicationGuardError):
            make_summary(held, settings)


class StorageWindowTests(unittest.TestCase):
    def test_scheduled_slot_handles_delayed_primary_and_backup_runs(self):
        self.assertEqual(
            scheduled_slot(datetime(2026, 8, 29, 0, 48, tzinfo=UTC), 30),
            datetime(2026, 8, 29, 0, 30, tzinfo=UTC),
        )
        self.assertEqual(
            scheduled_slot(datetime(2026, 8, 29, 0, 5, tzinfo=UTC), 30),
            datetime(2026, 8, 28, 23, 30, tzinfo=UTC),
        )

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

    def test_seven_day_window_lists_every_intermediate_day(self):
        class FakeStore:
            def __init__(self):
                self.prefixes = []

            def list_keys(self, prefix, *, limit=1000):
                del limit
                self.prefixes.append(prefix)
                return [f"{prefix}1200.json.gz"]

        store = FakeStore()
        now = datetime(2026, 8, 30, 12, 0, tzinfo=UTC)
        keys = recent_raw_keys(store, "raw", now=now, hours=168)
        self.assertEqual(len(store.prefixes), 8)
        self.assertIn("raw/2026/08/26/", store.prefixes)
        self.assertIn("raw/2026/08/29/", store.prefixes)
        self.assertEqual(len(keys), 8)

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


class PublicExportTests(unittest.TestCase):
    def test_exports_validated_live_summary(self):
        summary = {
            "meta": {"status": "live", "observed_at": "2026-08-28T13:54:45Z"},
            "rankings": {"live": [{"game_id": "minecraft"}], "last_24h": []},
        }

        class FakeStore:
            def get_json(self, key):
                self.key = key
                return summary

        store = FakeStore()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "data" / "latest.json"
            exported = export_latest(output, store=store)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), summary)
        self.assertEqual(store.key, "summary/latest.json")
        self.assertEqual(exported, summary)

    def test_rejects_empty_or_non_live_publication(self):
        with self.assertRaises(RuntimeError):
            validate_public_summary({"meta": {"status": "demo"}, "rankings": {"live": []}})


if __name__ == "__main__":
    unittest.main()



class CatalogSyncTests(unittest.TestCase):
    def test_observation_bundle_keeps_activity_and_unknown_alias(self):
        from src.catalog_sync import build_observation_bundle

        snapshots: list[list[dict[str, Any]]] = [[
            {
                "observed_at": "2026-08-29T00:00:00Z",
                "video_id": "video-1",
                "channel_id": "channel-1",
                "channel_title": "Streamer A",
                "raw_title": "Minecraft #マイクラ部",
                "canonical_game_id": "minecraft",
                "review_status": "auto",
            },
            {
                "observed_at": "2026-08-29T00:00:00Z",
                "video_id": "video-2",
                "channel_id": "channel-2",
                "channel_title": "Streamer B",
                "raw_title": "新作 #謎ゲーム",
                "canonical_game_id": None,
                "review_status": "hold",
            },
        ]]
        bundle = build_observation_bundle(
            snapshots,
            known_aliases={"minecraft"},
            snapshot_ids=["raw/2026/08/29/0000.json.gz"],
            generated_at="2026-08-29T01:00:00Z",
        )
        self.assertEqual(bundle["schema_version"], 2)
        self.assertEqual(
            bundle["snapshot_counts"]["raw/2026/08/29/0000.json.gz"]["games"],
            {"minecraft": 1},
        )
        self.assertEqual(
            bundle["snapshot_counts"]["raw/2026/08/29/0000.json.gz"]["aliases"],
            {"マイクラ部": 1, "謎ゲーム": 1},
        )
        self.assertEqual(bundle["games"]["minecraft"]["latest_streams"][0]["video_id"], "video-1")
        self.assertEqual(bundle["aliases"]["マイクラ部"]["candidate_game_ids"], ["minecraft"])
        self.assertEqual(bundle["aliases"]["謎ゲーム"]["candidate_game_ids"], [])
        self.assertEqual(bundle["aliases"]["謎ゲーム"]["latest_streams"][0]["channel_title"], "Streamer B")

    def test_game_candidate_can_be_kept_for_review_without_promotion(self):
        records = [
            {
                "observed_at": "2026-08-29T00:00:00Z",
                "channel_id": f"channel-{index}",
                "raw_title": "新作 #未確認ゲーム",
                "canonical_game_id": None,
                "review_status": "hold",
            }
            for index in range(5)
        ]
        state = update_dictionary_state(
            empty_dictionary_state(),
            records,
            known_aliases=set(),
            promote_game_candidates=False,
        )
        self.assertEqual(state["learned_games"], {})
        self.assertIn("未確認ゲーム", state["game_candidates"])

import test from "node:test";
import assert from "node:assert/strict";
import { compareRankingRows, formatCutoff, formatNumber, formatObservationPoint, rankingSortKey, statusPresentation } from "../web/assets/format.js";

test("formatNumber keeps zero and rejects missing values", () => {
  assert.equal(formatNumber(0), "0");
  assert.equal(formatNumber(null), "—");
  assert.equal(formatNumber(1234.56, 1), "1,234.6");
});

test("ranking keys change with period", () => {
  assert.equal(rankingSortKey("live", "streamers"), "live_streamers");
  assert.equal(rankingSortKey("live", "viewers"), "current_viewers");
  assert.equal(rankingSortKey("last_24h", "viewers"), "viewer_hours");
  assert.equal(rankingSortKey("last_24h", "density"), "view_delta");
});

test("demo is explicitly disclosed", () => {
  assert.equal(statusPresentation("demo").label, "DEMO DATA");
  assert.match(statusPresentation("stale").note, /最後に成功/);
  assert.equal(statusPresentation("probe").label, "LIVE PROBE");
});

test("streamer sorting uses viewers as the second priority", () => {
  const rows = [
    { display_name: "low", live_streamers: 1, current_viewers: 10 },
    { display_name: "high", live_streamers: 1, current_viewers: 100 },
    { display_name: "many", live_streamers: 2, current_viewers: 1 }
  ];
  rows.sort((a, b) => compareRankingRows(a, b, "live", "streamers"));
  assert.deepEqual(rows.map(row => row.display_name), ["many", "high", "low"]);
});

test("snapshot time and cutoff are written for Japanese readers", () => {
  assert.equal(formatObservationPoint("2026-08-28T14:09:00Z"), "8月28日 23時09分時点");
  assert.equal(
    formatCutoff({ min_subscribers: 1000, min_concurrent_viewers: 30, operator: "OR" }),
    "足切り：登録者1,000人以上 または 同接30人以上"
  );
});


import test from "node:test";
import assert from "node:assert/strict";
import { formatNumber, rankingSortKey, statusPresentation } from "../web/assets/format.js";

test("formatNumber keeps zero and rejects missing values", () => {
  assert.equal(formatNumber(0), "0");
  assert.equal(formatNumber(null), "—");
  assert.equal(formatNumber(1234.56, 1), "1,234.6");
});

test("ranking keys change with period", () => {
  assert.equal(rankingSortKey("live", "streamers"), "live_streamers");
  assert.equal(rankingSortKey("live", "viewers"), "current_viewers");
  assert.equal(rankingSortKey("last_24h", "viewers"), "viewer_hours");
});

test("demo is explicitly disclosed", () => {
  assert.equal(statusPresentation("demo").label, "DEMO DATA");
  assert.match(statusPresentation("stale").note, /最後に成功/);
});


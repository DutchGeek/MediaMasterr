import test from "node:test";
import assert from "node:assert/strict";

import { formatTorrentEta, formatTorrentProgress } from "./view.js";

test("formatTorrentEta handles qBittorrent ETA conventions", () => {
  assert.equal(formatTorrentEta(-1), "∞");
  assert.equal(formatTorrentEta(0), "Done");
  assert.equal(formatTorrentEta(60), "1m");
  assert.equal(formatTorrentEta(3700), "1h 1m");
});

test("formatTorrentProgress rounds to whole percentages", () => {
  assert.equal(formatTorrentProgress(0), "0%");
  assert.equal(formatTorrentProgress(0.421), "42%");
  assert.equal(formatTorrentProgress(0.995), "100%");
});

import test from "node:test";
import assert from "node:assert/strict";

import { asDisplayValue, nodeBadgeClass } from "./view.js";

test("asDisplayValue returns Unknown for empty values", () => {
  assert.equal(asDisplayValue(null), "Unknown");
  assert.equal(asDisplayValue(undefined), "Unknown");
  assert.equal(asDisplayValue("   "), "Unknown");
});

test("asDisplayValue returns trimmed text for non-empty values", () => {
  assert.equal(asDisplayValue(" qBittorrent "), "qBittorrent");
});

test("nodeBadgeClass maps known/unknown states", () => {
  assert.match(nodeBadgeClass("known"), /emerald/);
  assert.match(nodeBadgeClass("unknown"), /muted/);
});

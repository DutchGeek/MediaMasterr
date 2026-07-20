import test from "node:test";
import assert from "node:assert/strict";

import {
  confidenceBucket,
  isBlockedAsset,
  isNeedsReviewAsset,
  isReadyAsset,
  stageStats,
  summarizeBulkAction,
  toggleAssetSelection,
} from "./workspace-view.js";

test("confidence buckets are visually scannable", () => {
  assert.equal(confidenceBucket(95), "high");
  assert.equal(confidenceBucket(70), "medium");
  assert.equal(confidenceBucket(20), "low");
});

test("selection supports shift range and deselect", () => {
  const ids = ["a", "b", "c", "d"];
  let selected = new Set();

  selected = toggleAssetSelection(selected, ids, "b", {
    checked: true,
    shift: false,
    lastClickedId: null,
  });
  selected = toggleAssetSelection(selected, ids, "d", {
    checked: true,
    shift: true,
    lastClickedId: "b",
  });

  assert.deepEqual([...selected], ["b", "c", "d"]);

  selected = toggleAssetSelection(selected, ids, "c", {
    checked: false,
    shift: false,
    lastClickedId: "d",
  });
  assert.deepEqual([...selected], ["b", "d"]);
});

test("stage stats classify ready blocked and needs review", () => {
  const assets = [
    { confidence: 90, risk_level: "low", reason: "ok", current_status: "healthy" },
    { confidence: 45, risk_level: "high", reason: "failed import", current_status: "blocked" },
    { confidence: 65, risk_level: "medium", reason: "needs review", current_status: "pending" },
  ];

  const stats = stageStats(assets);
  assert.equal(stats.ready, 1);
  assert.equal(stats.blocked, 1);
  assert.equal(stats.needsReview, 1);
  assert.equal(stats.warnings, 1);
  assert.equal(isReadyAsset(assets[0]), true);
  assert.equal(isBlockedAsset(assets[1]), true);
  assert.equal(isNeedsReviewAsset(assets[2]), true);
});

test("bulk action summary aggregates preview and validation", () => {
  const summary = summarizeBulkAction([
    {
      preview: { estimated_recovery_bytes: 100 },
      validation: { valid: true, checks: [{ passed: true }] },
    },
    {
      preview: { estimated_recovery_bytes: 200 },
      validation: { valid: false, checks: [{ passed: false }, { passed: false }] },
    },
  ]);

  assert.equal(summary.total, 2);
  assert.equal(summary.validated, 1);
  assert.equal(summary.blocked, 1);
  assert.equal(summary.expectedSuccess, 1);
  assert.equal(summary.estimatedRecovery, 300);
  assert.equal(summary.warnings, 2);
});

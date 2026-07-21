import test from "node:test";
import assert from "node:assert/strict";

import {
  applyExecutionSessionToWorkspace,
  confidenceBucket,
  filterAndSortAssets,
  formatDuration,
  isBlockedAsset,
  isNeedsReviewAsset,
  isReadyAsset,
  predictNextWorkflowStage,
  stageStats,
  summarizeExecutionSession,
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
    {
      confidence: 90,
      risk_level: "low",
      reason: "ok",
      current_status: "healthy",
    },
    {
      confidence: 45,
      risk_level: "high",
      reason: "failed import",
      current_status: "blocked",
    },
    {
      confidence: 65,
      risk_level: "medium",
      reason: "needs review",
      current_status: "pending",
    },
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
      validation: {
        valid: false,
        checks: [{ passed: false }, { passed: false }],
      },
    },
  ]);

  assert.equal(summary.total, 2);
  assert.equal(summary.validated, 1);
  assert.equal(summary.blocked, 1);
  assert.equal(summary.expectedSuccess, 1);
  assert.equal(summary.estimatedRecovery, 300);
  assert.equal(summary.warnings, 2);
});

test("execution session moves completed cards and preserves moved selection", () => {
  const workspace = {
    workflow: {
      stages: [
        {
          key: "download",
          count: 1,
          assets: [
            {
              id: "rec-1",
              title: "Spider-Man",
              current_stage: "download",
              next_action: "import_media",
              current_status: "Queued",
              recommendation: "Import",
              filters: ["downloads"],
            },
          ],
        },
        { key: "import", count: 0, assets: [] },
        { key: "organize", count: 0, assets: [] },
        { key: "retention", count: 0, assets: [] },
        { key: "cleanup", count: 0, assets: [] },
        { key: "completed", count: 0, assets: [] },
      ],
      filters: [{ key: "downloads", title: "Downloads", count: 1 }],
    },
  };
  const selection = { download: new Set(["rec-1"]) };
  const session = {
    items: [
      {
        recommendation_id: "rec-1",
        status: "completed",
        message: "Imported",
      },
    ],
  };

  const next = applyExecutionSessionToWorkspace(
    workspace,
    session,
    new Set(),
    selection,
  );
  assert.ok(next.workspace?.workflow?.stages);
  const movedStages = next.workspace.workflow.stages;
  assert.ok(movedStages[1]);
  assert.ok(movedStages[1]?.assets?.[0]);
  assert.equal(movedStages[0]?.count, 0);
  assert.equal(movedStages[1]?.count, 1);
  assert.equal(movedStages[1]?.assets[0]?.current_stage, "import");
  assert.equal(next.stageSelections.import?.has("rec-1"), true);
});

test("failed execution updates asset in place without lane move", () => {
  const workspace = {
    workflow: {
      stages: [
        {
          key: "organize",
          count: 1,
          assets: [
            {
              id: "rec-2",
              title: "Batman",
              current_stage: "organize",
              next_action: "repair_identity",
              current_status: "Needs repair",
              recommendation: "Fix",
              filters: ["identity_issues"],
            },
          ],
        },
      ],
      filters: [{ key: "identity_issues", title: "Identity", count: 1 }],
    },
  };
  const session = {
    items: [
      {
        recommendation_id: "rec-2",
        status: "failed",
        message: "Filesystem locked",
      },
    ],
  };

  const next = applyExecutionSessionToWorkspace(
    workspace,
    session,
    new Set(),
    {},
  );
  assert.ok(next.workspace?.workflow?.stages);
  const failedStages = next.workspace.workflow.stages;
  assert.ok(failedStages[0]);
  assert.ok(failedStages[0]?.assets?.[0]);
  assert.equal(failedStages[0]?.count, 1);
  assert.equal(failedStages[0]?.assets[0]?.current_status, "Filesystem locked");
});

test("execution summary groups completed warnings and failures", () => {
  const summary = summarizeExecutionSession({
    elapsed_ms: 134000,
    summary: { recovered_space_bytes: 2048 },
    items: [
      { recommendation_id: "a", status: "completed" },
      { recommendation_id: "b", status: "blocked" },
      { recommendation_id: "c", status: "failed" },
    ],
  });

  assert.equal(summary.successfulCount, 1);
  assert.equal(summary.warningCount, 1);
  assert.equal(summary.failedCount, 1);
  assert.equal(summary.recoveredSpace, 2048);
  assert.equal(formatDuration(summary.elapsedMs), "2m 14s");
});

test("filtering and sorting preserves search and confidence semantics", () => {
  const assets = [
    {
      id: "a",
      title: "Spider-Man",
      confidence: 55,
      risk_level: "high",
      current_status: "blocked",
      reason: "failed import",
      estimated_space_recovery: 10,
      media_type: "movie",
      filters: ["downloads"],
    },
    {
      id: "b",
      title: "Batman",
      confidence: 90,
      risk_level: "low",
      current_status: "healthy",
      reason: "ok",
      estimated_space_recovery: 20,
      media_type: "movie",
      filters: ["downloads"],
    },
  ];
  const filtered = filterAndSortAssets(assets, {
    search: "bat",
    readiness: "all",
    sortBy: "title",
    sortOrder: "asc",
  });
  assert.deepEqual(
    filtered.map((row) => row.id),
    ["b"],
  );
  assert.equal(
    predictNextWorkflowStage({
      current_stage: "cleanup",
      next_action: "delete_files",
    }),
    "completed",
  );
});

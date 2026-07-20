/**
 * @typedef {Object} WorkspaceAsset
 * @property {string=} id
 * @property {string=} title
 * @property {string | null=} media_type
 * @property {string | null=} risk_level
 * @property {number | null=} confidence
 * @property {string=} reason
 * @property {string=} current_status
 * @property {string=} current_stage
 * @property {string=} next_action
 * @property {number=} estimated_space_recovery
 * @property {string[]=} filters
 * @property {string=} recommendation
 */

/**
 * @typedef {{ key: string, title?: string, description?: string, count?: number, assets?: WorkspaceAsset[] }} WorkflowStage
 */

/**
 * @typedef {{ workflow?: { stages?: WorkflowStage[], filters?: Array<{key: string, title: string, count: number}> } }} WorkspaceResponse
 */

/**
 * @typedef {{ recommendation_id: string, title?: string, status?: string, message?: string, estimated_recovery_bytes?: number, stages?: Array<{ key: string, label: string, status: string, detail?: string | null }> }} ExecutionItem
 */

/**
 * @typedef {{ elapsed_ms?: number, items?: ExecutionItem[], summary?: { successful?: number, warnings?: number, failed?: number, recovered_space_bytes?: number, elapsed_ms?: number } }} ExecutionSession
 */

/** @typedef {Record<string, Set<string>>} StageSelectionMap */

/** @param {number | null | undefined} confidence */
export function confidenceBucket(confidence) {
  const value = Number(confidence ?? 0);
  if (value >= 85) return "high";
  if (value >= 60) return "medium";
  return "low";
}

/** @param {number | null | undefined} confidence */
export function confidenceLabel(confidence) {
  const bucket = confidenceBucket(confidence);
  if (bucket === "high") return "High";
  if (bucket === "medium") return "Medium";
  return "Low";
}

/** @param {number | null | undefined} confidence */
export function confidenceBarClass(confidence) {
  const bucket = confidenceBucket(confidence);
  if (bucket === "high") return "bg-emerald-500";
  if (bucket === "medium") return "bg-amber-500";
  return "bg-rose-500";
}

/** @param {string | null | undefined} value */
export function riskLabel(value) {
  const lowered = String(value || "").toLowerCase();
  if (lowered.includes("high")) return "High";
  if (lowered.includes("medium")) return "Medium";
  return "Low";
}

/** @param {WorkspaceAsset} asset */
export function inferCategory(asset) {
  const title = String(asset?.title || "").toLowerCase();
  if (title.includes("anime")) return "anime";
  if (title.includes("collection")) return "collections";
  if (asset?.media_type === "movie") return "movies";
  if (asset?.media_type === "series") return "series";
  return "collections";
}

/** @param {WorkspaceAsset} asset */
export function isReadyAsset(asset) {
  return ["low", "safe"].includes(String(asset?.risk_level || "").toLowerCase()) &&
    Number(asset?.confidence || 0) >= 70;
}

/** @param {WorkspaceAsset} asset */
export function isBlockedAsset(asset) {
  const text = `${asset?.reason || ""} ${asset?.current_status || ""}`.toLowerCase();
  return text.includes("failed") || text.includes("blocked") || text.includes("missing");
}

/** @param {WorkspaceAsset} asset */
export function isNeedsReviewAsset(asset) {
  return !isReadyAsset(asset) && !isBlockedAsset(asset);
}

/** @param {WorkspaceAsset[] | undefined | null} assets */
export function stageStats(assets) {
  const rows = Array.isArray(assets) ? assets : [];
  const out = { ready: 0, blocked: 0, needsReview: 0, warnings: 0 };
  for (const asset of rows) {
    if (isBlockedAsset(asset)) out.blocked += 1;
    else if (isReadyAsset(asset)) out.ready += 1;
    else out.needsReview += 1;

    if (confidenceBucket(asset?.confidence) === "low") {
      out.warnings += 1;
    }
  }
  return out;
}

/**
 * @param {Set<string> | undefined | null} selectedIds
 * @param {string[] | undefined | null} orderedIds
 * @param {string} clickedId
 * @param {{shift?: boolean; lastClickedId?: string | null; checked?: boolean}=} opts
 */
export function toggleAssetSelection(selectedIds, orderedIds, clickedId, opts = {}) {
  const next = new Set(selectedIds || []);
  const ids = Array.isArray(orderedIds) ? orderedIds : [];
  const { shift = false, lastClickedId = null, checked = true } = opts;

  if (!shift || !lastClickedId || !ids.includes(lastClickedId)) {
    if (checked) next.add(clickedId);
    else next.delete(clickedId);
    return next;
  }

  const start = ids.indexOf(lastClickedId);
  const end = ids.indexOf(clickedId);
  if (start < 0 || end < 0) {
    if (checked) next.add(clickedId);
    else next.delete(clickedId);
    return next;
  }

  const from = Math.min(start, end);
  const to = Math.max(start, end);
  for (let i = from; i <= to; i += 1) {
    const id = ids[i];
    if (checked) next.add(id);
    else next.delete(id);
  }
  return next;
}

/**
 * @param {Array<{preview?: {estimated_recovery_bytes?: number}; validation?: {valid?: boolean; checks?: Array<{passed?: boolean}>}}>} results
 */
export function summarizeBulkAction(results) {
  const out = {
    total: 0,
    validated: 0,
    blocked: 0,
    warnings: 0,
    expectedSuccess: 0,
    estimatedRecovery: 0,
  };
  for (const row of results || []) {
    out.total += 1;
    const valid = Boolean(row?.validation?.valid);
    if (valid) {
      out.validated += 1;
      out.expectedSuccess += 1;
    } else {
      out.blocked += 1;
    }
    out.estimatedRecovery += Number(row?.preview?.estimated_recovery_bytes || 0);
    out.warnings += (row?.validation?.checks || []).filter((c) => !c.passed).length;
  }
  return out;
}

/** @param {number | null | undefined} value */
export function formatDuration(value) {
  const ms = Math.max(0, Number(value || 0));
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes <= 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

/**
 * @param {WorkspaceAsset[]} assets
 * @param {{search?: string, filterKey?: string | null, mediaType?: string, readiness?: string, sortBy?: string, sortOrder?: string}=} opts
 */
export function filterAndSortAssets(assets, opts = {}) {
  const {
    search = "",
    filterKey = null,
    mediaType = "all",
    readiness = "all",
    sortBy = "recovery",
    sortOrder = "desc",
  } = opts;
  const query = String(search || "").trim().toLowerCase();
  const rows = (assets || []).filter((asset) => {
    if (filterKey && !(asset?.filters || []).includes(filterKey)) return false;
    if (query) {
      const haystack = `${asset?.title || ""} ${asset?.reason || ""} ${asset?.current_status || ""}`.toLowerCase();
      if (!haystack.includes(query)) return false;
    }
    if (mediaType !== "all" && inferCategory(asset) !== mediaType) return false;
    if (readiness === "ready" && !isReadyAsset(asset)) return false;
    if (readiness === "blocked" && !isBlockedAsset(asset)) return false;
    if (readiness === "needs_review" && !isNeedsReviewAsset(asset)) return false;
    if (readiness === "high_confidence" && Number(asset?.confidence || 0) < 85) return false;
    if (readiness === "low_confidence" && Number(asset?.confidence || 0) >= 60) return false;
    return true;
  });
  const direction = sortOrder === "asc" ? 1 : -1;
  return rows.slice().sort((left, right) => {
    if (sortBy === "title") {
      return String(left?.title || "").localeCompare(String(right?.title || "")) * direction;
    }
    if (sortBy === "confidence") {
      return (Number(left?.confidence || 0) - Number(right?.confidence || 0)) * direction;
    }
    return (Number(left?.estimated_space_recovery || 0) - Number(right?.estimated_space_recovery || 0)) * direction;
  });
}

/** @param {string | null | undefined} stage */
export function stageTitle(stage) {
  /** @type {Record<string, string>} */
  const titles = {
    download: "Download",
    import: "Import",
    organize: "Organize",
    retention: "Retention",
    cleanup: "Cleanup",
    completed: "Completed",
  };
  return titles[String(stage || "")] || "Workflow";
}

/** @param {WorkspaceAsset} asset */
export function predictNextWorkflowStage(asset) {
  const action = String(asset?.next_action || "").toLowerCase();
  const current = String(asset?.current_stage || "");
  if (current === "download") return "import";
  if (current === "import") return "organize";
  if (current === "organize") {
    if (action.includes("delete") || action.includes("remove") || action.includes("cleanup")) {
      return "cleanup";
    }
    if (action.includes("protect") || action.includes("seed")) {
      return "retention";
    }
    return "completed";
  }
  if (current === "retention") return "cleanup";
  if (current === "cleanup") return "completed";
  return "completed";
}

/**
 * @param {WorkspaceResponse | null | undefined} workspace
 * @param {ExecutionSession | null | undefined} session
 * @param {Set<string> | undefined | null} appliedIds
 * @param {StageSelectionMap | undefined | null} stageSelections
 */
export function applyExecutionSessionToWorkspace(
  workspace,
  session,
  appliedIds,
  stageSelections,
) {
  if (!workspace?.workflow?.stages?.length || !session?.items?.length) {
    return {
      workspace,
      appliedIds: new Set(appliedIds || []),
      stageSelections: stageSelections || {},
    };
  }

  const alreadyApplied = new Set(appliedIds || []);
  /** @type {StageSelectionMap} */
  const nextSelections = {};
  for (const [key, ids] of Object.entries(stageSelections || {})) {
    nextSelections[key] = new Set(ids || []);
  }

  const stageMap = new Map();
  const nextStages = (workspace.workflow.stages || []).map((stage) => {
    const clone = {
      ...stage,
      assets: Array.isArray(stage.assets) ? stage.assets.slice() : [],
    };
    stageMap.set(stage.key, clone);
    return clone;
  });

  let changed = false;
  for (const item of session.items || []) {
    if (!item || alreadyApplied.has(item.recommendation_id)) continue;
    const sourceStage = nextStages.find((stage) =>
      (stage.assets || []).some((asset) => asset.id === item.recommendation_id),
    );
    if (!sourceStage) continue;
    const assetIndex = (sourceStage.assets || []).findIndex(
      (asset) => asset.id === item.recommendation_id,
    );
    if (assetIndex < 0) continue;
    const asset = sourceStage.assets[assetIndex];
    if (!asset?.id) continue;

    if (item.status === "completed") {
      const destinationKey = predictNextWorkflowStage(asset);
      const destinationStage = stageMap.get(destinationKey);
      sourceStage.assets.splice(assetIndex, 1);
      sourceStage.count = sourceStage.assets.length;
      const movedAsset = {
        ...asset,
        current_stage: destinationKey,
        current_status: item.message || "Completed",
        recommendation: item.message || asset.recommendation,
        next_action: item.message || asset.next_action,
      };
      if (destinationStage) {
        destinationStage.assets = [movedAsset, ...(destinationStage.assets || [])];
        destinationStage.count = destinationStage.assets.length;
      }
      if (nextSelections[sourceStage.key]?.has(asset.id)) {
        nextSelections[sourceStage.key].delete(asset.id);
        if (!nextSelections[destinationKey]) nextSelections[destinationKey] = new Set();
        nextSelections[destinationKey].add(asset.id);
      }
      alreadyApplied.add(item.recommendation_id);
      changed = true;
      continue;
    }

    if (item.status === "failed" || item.status === "blocked") {
      sourceStage.assets[assetIndex] = {
        ...asset,
        current_status: item.message || asset.current_status,
        recommendation: item.message || asset.recommendation,
      };
      alreadyApplied.add(item.recommendation_id);
      changed = true;
    }
  }

  if (!changed) {
    return { workspace, appliedIds: alreadyApplied, stageSelections: nextSelections };
  }

  const filterCounts = new Map();
  for (const stage of nextStages) {
    for (const asset of stage.assets || []) {
      for (const key of asset.filters || []) {
        filterCounts.set(key, Number(filterCounts.get(key) || 0) + 1);
      }
    }
  }
  const filters = (workspace.workflow.filters || []).map((row) => ({
    ...row,
    count: Number(filterCounts.get(row.key) || 0),
  }));
  return {
    workspace: {
      ...workspace,
      workflow: {
        ...workspace.workflow,
        stages: nextStages,
        filters,
      },
    },
    appliedIds: alreadyApplied,
    stageSelections: nextSelections,
  };
}

/**
 * @param {ExecutionSession | null | undefined} session
 */
export function summarizeExecutionSession(session) {
  const items = session?.items || [];
  const successful = items.filter((item) => item.status === "completed");
  const warnings = items.filter((item) => item.status === "blocked");
  const failed = items.filter((item) => item.status === "failed");
  return {
    successful,
    warnings,
    failed,
    successfulCount: successful.length,
    warningCount: warnings.length,
    failedCount: failed.length,
    recoveredSpace: Number(session?.summary?.recovered_space_bytes || 0),
    elapsedMs: Number(session?.summary?.elapsed_ms || session?.elapsed_ms || 0),
  };
}

/**
 * @typedef {Object} WorkspaceAsset
 * @property {string=} title
 * @property {string | null=} media_type
 * @property {string | null=} risk_level
 * @property {number | null=} confidence
 * @property {string=} reason
 * @property {string=} current_status
 */

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
